<template>
  <PanelShell :title="t('navigation.svc.title')" subtitle="上传音频、转换音色并测试 TTS/ASR 服务">
    <div class="voice-panel">
      <section class="voice-toolbar">
        <div>
          <strong>{{ runtimeSummary }}</strong>
        </div>
        <div class="toolbar-actions">
          <el-tag :type="selectedFile ? 'success' : 'info'">{{ selectedFile ? selectedFile.name : t('svcPanel.noAudio') }}</el-tag>
          <el-button :loading="settingsLoading" :disabled="settingsLoading" @click="loadSettings">{{ t('svcPanel.refreshSettings') }}</el-button>
        </div>
      </section>
      <el-alert v-if="voiceSaveStatusVisible" :title="voiceSaveStatusLabel" :description="voiceSaveStatusDetail" :type="voiceSaveAlertType" show-icon :closable="false" />

      <section class="voice-grid">
        <el-card class="voice-card svc-card" shadow="never">
          <template #header>
            <div class="card-header">
              <div>
                <strong>{{ svcProviderLabel }}</strong>
              </div>
              <el-tag :type="svcModelReady ? 'success' : 'warning'">{{ svcReadinessLabel }}</el-tag>
            </div>
          </template>

          <el-upload drag action="#" :auto-upload="false" :show-file-list="false" accept="audio/*" :on-change="handleFileChange">
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">{{ t('svcPanel.dropAudio') }}</div>
            <template #tip>
              <div class="el-upload__tip">{{ t('svcPanel.uploadTip') }}</div>
            </template>
          </el-upload>

          <el-form class="svc-form" label-position="top" @submit.prevent>
            <el-form-item :label="t('settings.svc.provider')">
              <el-select v-model="voiceConfig.svc.provider" @change="saveSvcProvider">
                <el-option label="SoulX-Singer-SVC Service" value="soulx-service" />
                <el-option :label="t('common.disabled')" value="disabled" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('settings.svc.baseUrl')">
              <el-input v-model="voiceConfig.svc.base_url" @change="saveSvcSettings({ base_url: String($event) })" />
            </el-form-item>
            <div class="form-row">
              <el-form-item :label="t('settings.svc.referenceAudioId')">
                <el-input-number v-model="voiceConfig.svc.speaker_id" :min="0" controls-position="right" @change="saveSvcSettings({ speaker_id: Number($event) })" />
              </el-form-item>
            </div>
            <el-form-item :label="t('svcPanel.pitchShiftValue', { value: `${conversionPitch > 0 ? '+' : ''}${conversionPitch}` })">
              <el-slider v-model="conversionPitch" :min="-36" :max="36" show-stops @change="saveSvcPitch" />
            </el-form-item>
          </el-form>

          <div class="execution-area">
            <el-button type="primary" :loading="isConverting" :disabled="!canStartConversion" @click="startConversion">
              {{ isConverting ? t('svcPanel.converting') : t('svcPanel.startConversion') }}
            </el-button>
            <el-alert
              v-if="svcReadinessMessage"
              :title="svcReadinessMessage"
              type="warning"
              show-icon
              :closable="false"
            />
            <el-alert v-if="conversionError" :title="conversionError" type="error" show-icon :closable="false" />
            <el-alert v-if="resultAudioUrl" :title="t('svcPanel.conversionComplete')" type="success" show-icon :closable="false" />
            <audio v-if="resultAudioUrl" :src="resultAudioUrl" controls class="audio-player"></audio>
          </div>
        </el-card>

        <div class="voice-side">
          <el-card class="voice-card" shadow="never">
            <template #header>
              <div class="card-header">
                <div>
              <strong>{{ t('settings.tts.service') }}</strong>
                </div>
                <el-button size="small" type="primary" plain :loading="testingTts" :disabled="testingTts" @click="testTts">{{ t('settings.tts.test') }}</el-button>
              </div>
            </template>
            <el-form label-position="top" @submit.prevent>
              <div class="form-row">
                <el-form-item :label="t('settings.tts.character')">
                  <el-input v-model="voiceConfig.tts.genie_character" :aria-label="t('settings.tts.character')" @change="saveTtsSettings({ genie_character: String($event) })" />
                </el-form-item>
                <el-form-item :label="t('settings.tts.modelDir')">
                  <el-input v-model="voiceConfig.tts.genie_model_dir" @change="saveTtsSettings({ genie_model_dir: String($event) })" />
                </el-form-item>
              </div>
              <div class="form-row">
                <el-form-item :label="t('settings.tts.lang')">
                  <el-select v-model="voiceConfig.tts.lang" @change="saveTtsSettings({ lang: String($event) })">
                    <el-option :label="t('settings.tts.lang.zh')" value="zh" />
                    <el-option :label="t('settings.tts.lang.ja')" value="ja" />
                    <el-option :label="t('settings.tts.lang.en')" value="en" />
                    <el-option :label="t('common.auto')" value="auto" />
                  </el-select>
                </el-form-item>
                <el-form-item :label="t('settings.tts.provider')">
                  <el-tag class="genie-provider-tag" type="success">{{ t('settings.tts.genieProvider') }}</el-tag>
                </el-form-item>
              </div>
              <el-form-item :label="t('settings.tts.referenceAudio')">
                <el-input v-model="voiceConfig.tts.ref_audio" :placeholder="t('settings.tts.referenceAudioPlaceholder')" @change="saveTtsSettings({ ref_audio: String($event) })" />
              </el-form-item>
              <el-form-item :label="t('settings.tts.referenceText')">
                <el-input v-model="voiceConfig.tts.ref_text" type="textarea" :rows="2" resize="none" @change="saveTtsSettings({ ref_text: String($event) })" />
              </el-form-item>
            </el-form>
          </el-card>

          <el-card class="voice-card" shadow="never">
            <template #header>
              <div class="card-header">
                <div>
              <strong>{{ t('settings.asr.title') }}</strong>
                </div>
                <el-tag type="info">Socket.IO</el-tag>
              </div>
            </template>
            <el-form label-position="top" @submit.prevent>
              <div class="form-row">
                <el-form-item :label="t('settings.asr.provider')">
                  <el-select
                    v-model="voiceConfig.asr.provider"
                    :aria-label="t('settings.asr.provider')"
                    @change="saveAsrSettings({ provider: String($event) as SettingsResponse['asr']['provider'] })"
                  >
                    <el-option label="SenseVoice Service" value="sensevoice-service" />
                    <el-option label="FunASR Service" value="funasr-service" />
                    <el-option label="OpenAI Compatible" value="openai-compatible" />
                    <el-option label="Sherpa ONNX" value="sherpa-onnx" />
                    <el-option label="Sherpa ONNX Streaming" value="sherpa-onnx-online" />
                    <el-option label="SenseVoice Local" value="sensevoice-local" />
                    <el-option :label="t('common.disabled')" value="disabled" />
                  </el-select>
                </el-form-item>
                <el-form-item v-if="voiceConfig.asr.provider !== 'disabled'" :label="t('settings.asr.languageHint')">
          <el-input v-model="voiceConfig.asr.language" placeholder="zh / ja / en" @change="saveAsrSettings({ language: String($event) })" />
                </el-form-item>
              </div>
              <div v-if="voiceConfig.asr.provider !== 'disabled'" class="form-row">
                <el-form-item v-if="voiceConfig.asr.provider !== 'sherpa-onnx-online'" :label="t('settings.asr.partialInterval')">
                  <el-input-number v-model="voiceConfig.asr.asr_partial_every" :min="1" :max="30" controls-position="right" @change="saveAsrSettings({ asr_partial_every: Number($event) })" />
                </el-form-item>
                <el-form-item :label="t('settings.asr.endpointSilenceCap', { value: voiceConfig.asr.vad_min_silence_ms })">
                  <el-input-number v-model="voiceConfig.asr.vad_min_silence_ms" :min="160" :max="1200" :step="32" controls-position="right" @change="saveAsrSettings({ vad_min_silence_ms: Number($event) })" />
                </el-form-item>
              </div>
              <el-form-item v-if="voiceConfig.asr.provider !== 'disabled'" :label="t('settings.asr.vadThreshold', { value: voiceConfig.asr.vad_threshold.toFixed(2) })">
                <el-slider v-model="voiceConfig.asr.vad_threshold" :min="0.1" :max="0.9" :step="0.05" @change="saveAsrSettings({ vad_threshold: Number($event) })" />
              </el-form-item>
            </el-form>
          </el-card>
        </div>
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { t } from '@/i18n'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { API_ORIGIN, requestJson, resolveBackendUrl } from '@/api/clients/http-client'
import { settingsClient, type SettingsResponse } from '@/api/clients/settings-client'
import { DEFAULT_VAD_MIN_SILENCE_MS } from '@/../shared/runtime-defaults'

interface SvcConvertResponse {
  status?: string
  audio_url?: string
  url?: string
  error?: string
}

type SaveTimeout = ReturnType<typeof window.setTimeout>
type SettingsPatch = Record<string, unknown>
type AlertType = 'success' | 'warning' | 'info' | 'error'
type TtsSettingsPatch = Partial<SettingsResponse['tts']>
type AsrSettingsPatch = Partial<SettingsResponse['asr']>
type SvcSettingsPatch = Partial<SettingsResponse['svc']>

const defaultVoiceConfig: Pick<SettingsResponse, 'tts' | 'asr' | 'svc'> = {
  tts: {
    genie_character: '',
    genie_model_dir: '',
    lang: 'zh',
    ref_audio: '',
    ref_text: '',
    device: 'cpu',
    quality: '质量优先',
    split: '智能切分',
    mode: '串行推理',
    save_mode: '禁用自动保存',
    provider: 'genie-tts',
  },
  asr: {
    provider: 'sherpa-onnx-online',
    base_url: '',
    api_key: '',
    timeout: 60,
    sensevoice_model: 'iic/SenseVoiceSmall',
    sensevoice_device: 'cpu',
    sherpa_model_path: '',
    sherpa_tokens_path: '',
    sherpa_num_threads: 2,
    sherpa_provider: 'cpu',
    language: 'zh',
    vad_threshold: 0.5,
    vad_min_silence_ms: DEFAULT_VAD_MIN_SILENCE_MS,
    asr_partial_every: 15,
  },
  svc: {
    provider: 'soulx-service',
    base_url: '',
    speaker_id: 0,
    pitch: 0,
    timeout: 120,
  },
}

const voiceConfig = reactive<Pick<SettingsResponse, 'tts' | 'asr' | 'svc'>>(structuredClone(defaultVoiceConfig))
const selectedFile = ref<File | null>(null)
const settingsLoading = ref(false)
const testingTts = ref(false)
const isConverting = ref(false)
const conversionPitch = ref(0)
const resultAudioUrl = ref('')
const conversionError = ref('')
const voiceSaveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const voiceSaveError = ref('')
const voiceLastSavedAt = ref('')
const voiceLastApplied = ref<string[]>([])
const pendingSavePatch = ref<SettingsPatch | null>(null)
let saveTimeout: SaveTimeout | null = null
let settingsLoadSequence = 0
let unmounted = false

const isPlainRecord = (value: unknown): value is SettingsPatch => {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const mergePatch = (base: SettingsPatch, patch: SettingsPatch): SettingsPatch => {
  const merged: SettingsPatch = { ...base }
  for (const [key, value] of Object.entries(patch)) {
    const existing = merged[key]
    merged[key] = isPlainRecord(existing) && isPlainRecord(value)
      ? mergePatch(existing, value)
      : value
  }
  return merged
}

const svcModelReady = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return false
  return Boolean(voiceConfig.svc.base_url.trim())
})
const svcProviderLabel = computed(() => voiceConfig.svc.provider === 'disabled' ? t('svcPanel.svcDisabled') : 'SoulX-Singer-SVC Service')
const svcReadinessLabel = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return t('svcPanel.svcDisabled')
  if (!voiceConfig.svc.base_url.trim()) return t('svcPanel.endpointMissing')
  return t('svcPanel.serviceConfigured')
})
const svcReadinessMessage = computed(() => {
  if (voiceConfig.svc.provider === 'disabled') return t('svcPanel.enableSvcFirst')
  if (!voiceConfig.svc.base_url.trim()) return t('svcPanel.configureEndpointFirst')
  return ''
})
const canStartConversion = computed(() => {
  return Boolean(selectedFile.value && svcModelReady.value && !isConverting.value)
})
const runtimeSummary = computed(() => `${t('settings.tts.genieProvider')} 路 ${voiceConfig.asr.provider} 路 ${voiceConfig.svc.provider}`)
const voiceSaveStatusVisible = computed(() => voiceSaveStatus.value !== 'idle')
const voiceSaveAlertType = computed<AlertType>(() => {
  if (voiceSaveStatus.value === 'error') return 'error'
  if (voiceSaveStatus.value === 'saving') return 'warning'
  if (voiceSaveStatus.value === 'saved') return 'success'
  return 'info'
})
const voiceSaveStatusLabel = computed(() => {
  if (voiceSaveStatus.value === 'saving') return t('settings.status.saving')
  if (voiceSaveStatus.value === 'error') return t('svcPanel.saveFailed')
  if (voiceSaveStatus.value === 'saved') return t('settings.status.saved')
  return ''
})
const voiceSaveStatusDetail = computed(() => {
  if (voiceSaveStatus.value === 'error') return voiceSaveError.value
  if (voiceSaveStatus.value === 'saving') return t('settings.status.savingShort')
  if (voiceLastApplied.value.length) return t('settings.status.applied', { items: voiceLastApplied.value.join(' / ') })
  if (voiceLastSavedAt.value) return t('settings.status.recent', { time: voiceLastSavedAt.value })
  return ''
})

const applySettings = (settings: SettingsResponse) => {
  Object.assign(voiceConfig.tts, settings.tts)
  voiceConfig.tts.provider = 'genie-tts'
  Object.assign(voiceConfig.asr, settings.asr)
  Object.assign(voiceConfig.svc, settings.svc)
  conversionPitch.value = settings.svc.pitch
}

const loadSettings = async () => {
  const requestId = ++settingsLoadSequence
  settingsLoading.value = true
  try {
    const settings = await settingsClient.load()
    if (unmounted || requestId !== settingsLoadSequence) return
    applySettings(settings)
  } catch (error) {
    if (unmounted || requestId !== settingsLoadSequence) return
    ElMessage.error(error instanceof Error ? error.message : t('svcPanel.loadFailed'))
  } finally {
    if (!unmounted && requestId === settingsLoadSequence) settingsLoading.value = false
  }
}

const errorMessage = (error: unknown, fallback: string) => {
  return error instanceof Error ? error.message : fallback
}

const savePatch = async (patch: SettingsPatch) => {
  if (!unmounted) {
    voiceSaveStatus.value = 'saving'
    voiceSaveError.value = ''
  }
  try {
    const result = await settingsClient.save(patch)
    if (unmounted) return true
    voiceLastSavedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    voiceLastApplied.value = result.runtime_applied || result.runtime_changed || []
    voiceSaveStatus.value = 'saved'
    return true
  } catch (error) {
    if (unmounted) {
      console.error('[SVCPanel Save]:', error)
      return false
    }
    voiceSaveError.value = errorMessage(error, t('svcPanel.saveFailed'))
    voiceSaveStatus.value = 'error'
    ElMessage.error(voiceSaveError.value)
    return false
  }
}

const scheduleSave = (patch: SettingsPatch) => {
  if (unmounted) return
  if (saveTimeout) clearTimeout(saveTimeout)
  pendingSavePatch.value = pendingSavePatch.value
    ? mergePatch(pendingSavePatch.value, patch)
    : patch

  saveTimeout = setTimeout(async () => {
    const currentPatch = pendingSavePatch.value
    pendingSavePatch.value = null
    if (currentPatch) await savePatch(currentPatch)
  }, 800)
}

const flushPendingSave = async () => {
  if (!pendingSavePatch.value) return true
  if (saveTimeout) {
    clearTimeout(saveTimeout)
    saveTimeout = null
  }
  const currentPatch = pendingSavePatch.value
  pendingSavePatch.value = null
  return savePatch(currentPatch)
}

const saveTtsSettings = (patch: TtsSettingsPatch) => {
  voiceConfig.tts.provider = 'genie-tts'
  scheduleSave({ tts: patch })
}

const saveAsrSettings = (patch: AsrSettingsPatch) => {
  scheduleSave({ asr: patch })
}

const saveSvcSettings = (patch: SvcSettingsPatch) => {
  scheduleSave({ svc: patch })
}

const saveSvcProvider = (value: string | number | boolean) => {
  const provider = String(value) as SettingsResponse['svc']['provider']
  voiceConfig.svc.provider = provider
  saveSvcSettings({ provider })
}

const saveSvcPitch = (value: number | number[]) => {
  const pitch = Array.isArray(value) ? value[0] ?? 0 : value
  voiceConfig.svc.pitch = pitch
  saveSvcSettings({ pitch })
}

const testTts = async () => {
  if (testingTts.value) return
  if (!(await flushPendingSave())) return
  testingTts.value = true
  try {
    const result = await settingsClient.testTts()
    if (result.ok === false) {
      ElMessage.error(result.message || t('svcPanel.ttsFailed'))
      return
    }
    ElMessage.success(result.message || t('svcPanel.ttsDone'))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('svcPanel.ttsFailed'))
  } finally {
    testingTts.value = false
  }
}

const handleFileChange = (uploadFile: UploadFile) => {
  selectedFile.value = uploadFile.raw ?? null
  resultAudioUrl.value = ''
  conversionError.value = ''
}

const normalizeAudioUrl = async (audioUrl: string) => {
  if (!audioUrl) return ''
  if (audioUrl.startsWith('http://') || audioUrl.startsWith('https://')) return audioUrl
  return resolveBackendUrl(audioUrl)
}

const startConversion = async () => {
  if (isConverting.value) return
  if (!selectedFile.value) {
    ElMessage.warning(t('svcPanel.selectAudioFirst'))
    return
  }
  if (!svcModelReady.value) {
    ElMessage.warning(svcReadinessMessage.value || t('svcPanel.waitingService'))
    return
  }
  if (voiceConfig.svc.pitch !== conversionPitch.value) {
    voiceConfig.svc.pitch = conversionPitch.value
    saveSvcSettings({ pitch: conversionPitch.value })
  }
  if (!(await flushPendingSave())) return
  isConverting.value = true
  resultAudioUrl.value = ''
  conversionError.value = ''
  try {
    const formData = new FormData()
    formData.append('file', selectedFile.value)
    formData.append('speaker_id', String(voiceConfig.svc.speaker_id))
    formData.append('pitch', String(conversionPitch.value))
    const result = await requestJson<SvcConvertResponse>(`${API_ORIGIN}/svc/convert`, { method: 'POST', body: formData })
    if (result.status === 'error') {
      throw new Error(result.error || t('svcPanel.requestFailed', { status: 'error' }))
    }
    resultAudioUrl.value = await normalizeAudioUrl(result.audio_url || result.url || '')
    if (!resultAudioUrl.value) {
      conversionError.value = t('svcPanel.requestDoneNoAudio')
      return
    }
    ElMessage.success(t('svcPanel.svcComplete'))
  } catch (error) {
    conversionError.value = error instanceof Error ? error.message : String(error)
    ElMessage.error(conversionError.value)
  } finally {
    isConverting.value = false
  }
}

onMounted(() => {
  void loadSettings()
})

onUnmounted(() => {
  unmounted = true
  settingsLoadSequence += 1
  if (saveTimeout) clearTimeout(saveTimeout)
  const currentPatch = pendingSavePatch.value
  pendingSavePatch.value = null
  if (currentPatch) void savePatch(currentPatch)
})
</script>

<style scoped>
.voice-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.voice-toolbar,
.voice-card {
  border: 1px solid var(--yui-border);
  background: var(--yui-surface);
  box-shadow: var(--yui-shadow-card);
}

.voice-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-radius: var(--yui-radius-card);
  padding: 14px 16px;
}

.voice-toolbar > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.voice-toolbar strong,
.card-header strong {
  color: var(--yui-text);
  font-size: 16px;
}

.toolbar-actions,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.section-kicker {
  color: var(--yui-accent);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.voice-grid {
  display: grid;
  grid-template-columns: minmax(360px, 0.95fr) minmax(420px, 1.2fr);
  gap: 16px;
  min-height: 0;
}

.voice-side {
  display: grid;
  gap: 16px;
}

.genie-provider-tag {
  min-height: 32px;
  align-items: center;
}

.upload-icon {
  margin-bottom: 8px;
  color: var(--el-color-primary);
  font-size: 42px;
}

:deep(.el-upload-dragger) {
  border-color: var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

:deep(.el-upload-dragger:hover) {
  border-color: var(--yui-accent);
  background: var(--yui-accent-soft);
}

.svc-form,
.execution-area {
  margin-top: 16px;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.form-row.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.execution-area {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.audio-player {
  width: 100%;
}

@media (max-width: 1180px) {
  .voice-grid,
  .form-row,
  .form-row.three {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .voice-toolbar,
  .card-header,
  .toolbar-actions {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
