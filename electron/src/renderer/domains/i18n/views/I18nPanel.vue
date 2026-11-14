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
          <el-button type="primary" :loading="syncingLocale" :disabled="localeBusy || !selectedFrontendLocale" @click="applyAppLocale">{{ t('i18n.syncAppLanguage') }}</el-button>
          <el-tag>{{ localeLabel(locale) }} · {{ locale }}</el-tag>
          <el-tag v-if="currentLocale" type="info">{{ t('i18n.currentBackend') }}: {{ currentLocale }}</el-tag>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <strong>{{ t('i18n.backend.title') }}</strong>
            <el-button type="primary" :loading="loading" :disabled="loading || localeBusy" @click="loadAll">{{ t('i18n.refresh') }}</el-button>
          </div>
        </template>
        <div class="language-row">
          <el-select v-model="selectedLocale" :placeholder="t('language.select')" class="locale-select">
            <el-option v-for="localeOption in locales" :key="localeOption" :label="backendLocaleLabel(localeOption)" :value="localeOption" />
          </el-select>
          <el-button type="primary" :loading="applyingBackendLocale" :disabled="localeBusy || !selectedLocale" @click="applyBackendLocale">{{ t('i18n.backendOnly') }}</el-button>
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
          <el-button plain :loading="lookupKind === 'message'" @click="lookupMessage">{{ t('i18n.lookup.message') }}</el-button>
          <el-button plain :loading="lookupKind === 'error'" @click="lookupError">{{ t('i18n.lookup.error') }}</el-button>
        </div>
        <el-alert v-if="lastLookup" :title="lastLookup" :type="lookupFailed ? 'error' : 'info'" show-icon :closable="false" />
        <details v-if="Object.keys(messages).length" class="messages-details">
          <summary>{{ t('misc.currentLocaleContent') }}</summary>
          <pre class="messages-preview">{{ messagesPreview }}</pre>
        </details>
        <el-empty v-else :description="t('misc.translationsNotLoaded')" :image-size="48" />
      </el-card>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { ElAlert } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { useI18nDiagnostics } from '../composables/useI18nDiagnostics'
import PanelShell from '@/shared/components/panel/PanelShell.vue'

const {
  loading, locales, currentLocale, selectedLocale, messages, messageKey, lastLookup, lookupFailed, loadError,
  syncingLocale, applyingBackendLocale, localeBusy, lookupKind, locale, localeLabel, supportedLocales,
  selectedFrontendLocale, messagesPreview, backendLocaleLabel, loadAll, applyAppLocale, applyBackendLocale,
  lookupMessage, lookupError, t,
} = useI18nDiagnostics()
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

.messages-details summary {
  cursor: pointer;
  color: var(--yui-muted);
  font-size: 12px;
}

.messages-details .messages-preview {
  margin-top: 10px;
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
