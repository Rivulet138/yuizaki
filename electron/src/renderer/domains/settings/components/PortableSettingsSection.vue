<template>
  <section class="portable-settings" aria-labelledby="portable-settings-title">
    <header class="portable-heading">
      <div>
        <h2 id="portable-settings-title">{{ t('settings.portable.title') }}</h2>
        <p>{{ t('settings.portable.description') }}</p>
      </div>
      <el-tag type="info">JSON</el-tag>
    </header>

    <el-alert
      :title="t('settings.portable.secretNote')"
      type="info"
      show-icon
      :closable="false"
    />

    <div class="portable-actions">
      <el-button type="primary" :loading="exporting" @click="exportSettings">
        <el-icon><Download /></el-icon>{{ t('settings.portable.export') }}
      </el-button>
      <el-button :loading="importing" @click="importInput?.click()">
        <el-icon><Upload /></el-icon>{{ t('settings.portable.import') }}
      </el-button>
      <el-button plain @click="openOnboarding">
        <el-icon><Refresh /></el-icon>{{ t('onboarding.reopen') }}
      </el-button>
      <input
        ref="importInput"
        class="portable-file-input"
        type="file"
        accept="application/json,.json"
        :aria-label="t('settings.portable.import')"
        @change="handleImportFile"
      />
    </div>

    <p v-if="statusMessage" class="portable-status" :class="`is-${statusType}`" :role="statusType === 'error' ? 'alert' : 'status'">
      {{ statusMessage }}
    </p>

    <dl class="portable-facts">
      <div>
        <dt>{{ t('settings.portable.scopeLabel') }}</dt>
        <dd>{{ t('settings.portable.scope') }}</dd>
      </div>
      <div>
        <dt>{{ t('settings.portable.secretLabel') }}</dt>
        <dd>{{ t('settings.portable.secretValue') }}</dd>
      </div>
      <div>
        <dt>{{ t('settings.portable.applyLabel') }}</dt>
        <dd>{{ t('settings.portable.applyValue') }}</dd>
      </div>
    </dl>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Download, Refresh, Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { settingsClient } from '@/api/clients/settings-client'
import { t } from '@/i18n'
import { openOnboarding } from '@/domains/onboarding/onboardingEvents'

const props = defineProps<{
  beforeImport?: () => Promise<boolean>
}>()
const emit = defineEmits<{ imported: [] }>()
const importInput = ref<HTMLInputElement | null>(null)
const exporting = ref(false)
const importing = ref(false)
const statusMessage = ref('')
const statusType = ref<'success' | 'error'>('success')

const setStatus = (message: string, type: 'success' | 'error' = 'success'): void => {
  statusMessage.value = message
  statusType.value = type
}

const exportSettings = async (): Promise<void> => {
  if (exporting.value) return
  exporting.value = true
  statusMessage.value = ''
  try {
    const blob = await settingsClient.exportBlob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `yuizaki-settings-${new Date().toISOString().slice(0, 10)}.json`
    anchor.click()
    URL.revokeObjectURL(url)
    setStatus(t('settings.portable.exported'))
  } catch (error) {
    setStatus(error instanceof Error ? error.message : t('settings.portable.failed'), 'error')
  } finally {
    exporting.value = false
  }
}

const handleImportFile = async (event: Event): Promise<void> => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || importing.value) return
  importing.value = true
  statusMessage.value = ''
  try {
    if (props.beforeImport && !(await props.beforeImport())) {
      throw new Error(t('settings.messages.saveFailed'))
    }
    const parsed: unknown = JSON.parse(await file.text())
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error(t('settings.portable.invalidFile'))
    }
    const result = await settingsClient.importPayload(parsed as Record<string, unknown>)
    emit('imported')
    const applied = result.runtime_applied?.length ?? 0
    setStatus(t('settings.portable.imported', { count: applied }))
    ElMessage.success(t('settings.portable.imported', { count: applied }))
  } catch (error) {
    setStatus(error instanceof Error ? error.message : t('settings.portable.failed'), 'error')
  } finally {
    importing.value = false
  }
}
</script>

<style scoped>
.portable-settings { display: grid; gap: 16px; min-width: 0; }
.portable-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.portable-heading h2 { margin: 0; color: var(--yui-text); font-size: 16px; }
.portable-heading p { max-width: 65ch; margin: 5px 0 0; color: var(--yui-muted); font-size: 13px; line-height: 1.5; }
.portable-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.portable-file-input { display: none; }
.portable-status { margin: 0; overflow-wrap: anywhere; color: #15803d; font-size: 13px; }
.portable-status.is-error { color: #b91c1c; }
.portable-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 0; }
.portable-facts div { min-width: 0; padding: 12px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface-muted); }
.portable-facts dt { color: var(--yui-muted); font-size: 12px; }
.portable-facts dd { margin: 5px 0 0; overflow-wrap: anywhere; color: var(--yui-text); font-size: 13px; line-height: 1.45; }

@media (max-width: 680px) {
  .portable-facts { grid-template-columns: minmax(0, 1fr); }
  .portable-actions :deep(.el-button) { flex: 1 1 100%; margin-left: 0; }
}
</style>
