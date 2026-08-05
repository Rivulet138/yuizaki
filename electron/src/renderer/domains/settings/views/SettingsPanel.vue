<template>
  <PanelShell :title="t('settings.title')" tone="admin">
    <AsyncState :loading="settingsRequest.loading && !settings" :empty="!settings && !settingsRequest.error" :empty-text="t('settings.empty')">
      <div class="settings-panel">
        <el-alert
          v-if="settingsRequest.error"
          :title="settingsRequest.error"
          type="error"
          show-icon
          :closable="false"
        />
        <el-alert
          v-if="saveBusy || updateRequest.error || lastSavedAt"
          :title="saveStatusLabel"
          :description="saveStatusDetail"
          :type="saveStatusType"
          show-icon
          :closable="false"
        />

        <el-card class="settings-access-card" shadow="never">
          <div class="access-stack">
            <div class="access-row">
              <div>
                <strong>{{ t('settings.access.title') }}</strong>
              </div>
              <div class="access-controls">
                <el-input
                  v-model="adminTokenInput"
                  class="admin-token-input"
                  type="password"
                  show-password
                  :placeholder="t('settings.access.placeholder')"
                  @keyup.enter="saveAdminToken"
                />
                <el-button type="primary" plain :loading="adminTokenRequest.loading" @click="saveAdminToken">{{ t('settings.access.unlock') }}</el-button>
                <el-button plain :loading="adminTokenRequest.loading" @click="clearAdminToken">{{ t('common.clear') }}</el-button>
                <el-tag :type="adminTokenConfigured ? 'success' : 'info'">{{ adminTokenConfigured ? t('settings.access.tokenSet') : t('settings.access.tokenNotSet') }}</el-tag>
              </div>
            </div>
            <div class="access-divider" aria-hidden="true" />
            <div class="access-row backend-token-row">
              <div>
                <strong>{{ t('settings.backendToken.title') }}</strong>
                <div v-if="backendTokenStatus" class="access-token-details">
                  <el-tag size="small" type="info">{{ t('settings.backendToken.source') }} · {{ backendTokenSourceLabel }}</el-tag>
                  <el-tag v-if="backendTokenPreview" size="small" type="info">{{ t('settings.backendToken.preview') }} · {{ backendTokenPreview }}</el-tag>
                  <el-tag v-if="backendTokenRequiresRestart" size="small" type="warning">{{ t('settings.backendToken.restartRequired') }}</el-tag>
                </div>
              </div>
              <div class="access-controls">
                <el-input
                  v-model="backendTokenInput"
                  class="backend-token-input"
                  type="password"
                  show-password
                  :placeholder="t('settings.backendToken.placeholder')"
                  @keyup.enter="saveBackendToken"
                />
                <el-button type="primary" plain :loading="backendTokenBusy" @click="saveBackendToken">{{ t('settings.backendToken.save') }}</el-button>
                <el-button plain :loading="backendTokenBusy" @click="resetBackendToken">{{ t('settings.backendToken.reset') }}</el-button>
                <el-tag :type="backendTokenRequiresRestart ? 'warning' : backendTokenConfigured ? 'success' : 'info'">
                  {{ backendTokenRequiresRestart ? t('settings.backendToken.restartRequired') : backendTokenConfigured ? t('settings.backendToken.tokenSet') : t('settings.backendToken.tokenNotSet') }}
                </el-tag>
              </div>
            </div>
          </div>
        </el-card>

        <el-tabs v-model="activeSection" type="border-card">
          <el-tab-pane :label="t('settings.tabs.llm')" name="llm">
            <el-card class="llm-settings-card" shadow="never">
              <template #header>
                <div class="card-header">
                  <div class="header-title">
                    <span>{{ t('settings.llm.service') }}</span>
                  </div>
                  <div class="llm-toolbar">
                    <div class="llm-status-strip">
                      <el-tag :type="hasLlmEndpoint ? 'success' : 'warning'">{{ hasLlmEndpoint ? t('common.configured') : t('settings.tts.incomplete') }}</el-tag>
                      <el-tag :type="hasLlmApiKey ? 'success' : 'info'">{{ llmApiKeyTagLabel }}</el-tag>
                      <el-tag :type="llmDetectionTagType">{{ llmDetectionStatus }}</el-tag>
                      <el-tag v-if="llmModels.length" type="info">{{ t('settings.llm.modelsCount', { count: llmModels.length }) }}</el-tag>
                    </div>
                    <div class="llm-actions">
                      <div class="llm-action-group">
                        <el-button plain :loading="llmImporting" @click="triggerLlmImport">
                          <el-icon><Upload /></el-icon>
                          {{ t('settings.llm.importProfile') }}
                        </el-button>
                        <el-button plain @click="downloadLlmProfileTemplate">
                          <el-icon><Document /></el-icon>
                          {{ t('settings.llm.templateProfile') }}
                        </el-button>
                        <el-button plain :loading="llmExporting" @click="exportLlmProfile">
                          <el-icon><Download /></el-icon>
                          {{ t('settings.llm.exportProfile') }}
                        </el-button>
                      </div>
                      <div class="llm-action-group">
                        <el-button plain :loading="localDiscoveryRequest.loading" @click="applyLocalLlmDiscovery">
                          <el-icon><Connection /></el-icon>
                          {{ t('settings.discovery.detectLocal') }}
                        </el-button>
                        <el-button plain :loading="llmModelsRequest.loading" :disabled="!canRequestLlmModels" @click="discoverLlmModels({ forceAutoSelect: true, manual: true })">
                          <el-icon><Refresh /></el-icon>
                          {{ t('settings.llm.detectModels') }}
                        </el-button>
                        <el-button type="primary" plain :loading="testLlmRequest.loading" :disabled="!hasLlmEndpoint" @click="handleTestLlm">
                          <el-icon><Connection /></el-icon>
                          {{ t('settings.llm.test') }}
                        </el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </template>
              <input ref="llmImportInput" class="sr-only-input" type="file" accept="application/json,.json" @change="handleLlmImportFile" />
              <el-form label-position="top" @submit.prevent>
                <div class="llm-workspace">
                  <aside class="llm-profile-rail">
                    <div class="profile-rail-head">
                      <strong>{{ t('settings.llm.profileTitle') }}</strong>
                    </div>
                    <el-radio-group v-model="llmProviderPreset" class="provider-stack" :aria-label="t('settings.llm.providerPreset')" @change="applyLlmProviderPreset">
                      <el-radio-button v-for="option in llmProviderOptionRows" :key="option.value" :label="option.label" :value="option.value">
                        <span class="provider-option-label">
                          <strong>{{ option.label }}</strong>
                          <small :class="`status-${option.statusClass}`">{{ option.status }}</small>
                        </span>
                      </el-radio-button>
                    </el-radio-group>
                    <el-button class="profile-reset-button" plain @click="resetCurrentLlmProfile">
                      <el-icon><Refresh /></el-icon>
                      {{ t('settings.llm.resetProfile') }}
                    </el-button>
                    <div class="profile-card">
                      <span>{{ t('settings.llm.activeProfile') }}</span>
                      <strong>{{ activeLlmProfileLabel }}</strong>
                    </div>
                    <div class="credential-card" :class="{ empty: !hasLlmApiKey }">
                      <span>{{ t('settings.llm.credentialTitle') }}</span>
                      <strong>{{ llmAuthSummary }}</strong>
                    </div>
                    <div class="llm-connection-summary">
                      <div class="summary-row">
                        <span>{{ t('settings.llm.summaryEndpoint') }}</span>
                        <strong>{{ llmEndpointSummary }}</strong>
                      </div>
                      <div class="summary-row">
                        <span>{{ t('settings.llm.summaryModel') }}</span>
                        <strong>{{ llmModelSummary }}</strong>
                      </div>
                      <div class="summary-row">
                        <span>{{ t('settings.llm.summaryAuth') }}</span>
                        <strong>{{ llmAuthSummary }}</strong>
                      </div>
                    </div>
                  </aside>

                  <div class="llm-main-form">
                    <div class="subsection-title">{{ t('settings.llm.sectionConnection') }}</div>
                    <div class="form-grid">
                      <el-form-item :label="t('settings.llm.baseUrl')">
                        <el-input v-model="form.llm.base_url" name="llm-base-url" @change="handleLlmEndpointChange('base_url', $event)" @keyup.enter="scheduleLlmModelDiscovery">
                          <template #append>{{ llmEndpointAppendLabel }}</template>
                        </el-input>
                      </el-form-item>
                      <el-form-item v-if="llmProviderNeedsApiKey" :label="t('settings.llm.apiKeyLabel')">
                        <el-input v-model="form.llm.api_key" type="password" show-password @change="handleLlmEndpointChange('api_key', $event)" @keyup.enter="scheduleLlmModelDiscovery" />
                      </el-form-item>
                    </div>

                    <el-form-item :label="t('settings.llm.modelName')">
                      <el-select
                        v-model="form.llm.model"
                        class="full-width"
                        filterable
                        allow-create
                        default-first-option
                        :loading="llmModelsRequest.loading"
                        @focus="scheduleLlmModelDiscovery"
                        @change="handleLlmModelChange"
                      >
                        <el-option v-for="model in llmModelSelectOptions" :key="model" :label="model" :value="model" />
                      </el-select>
                      <p v-if="llmModelStatusLabel" class="field-hint" :class="{ error: llmModelsRequest.error }">{{ llmModelStatusLabel }}</p>
                      <div v-if="form.llm.model.trim()" class="model-capability-panel">
                        <div class="model-capability-head">
                          <strong>模型能力</strong>
                          <span>
                            {{ modelCapabilitySourceLabel }}
                            <a
                              v-if="currentModelCapabilities.metadata"
                              :href="currentModelCapabilities.metadata.documentationUrl"
                              target="_blank"
                              rel="noreferrer"
                            >来源</a>
                          </span>
                        </div>
                        <div class="model-capability-strip">
                          <el-tag :type="modelLatencyTagType" size="small">{{ modelLatencyLabel }}</el-tag>
                          <el-tag
                            v-for="item in modelCapabilityRows"
                            :key="item.key"
                            :type="capabilityTagType(item.support)"
                            size="small"
                          >
                            {{ item.label }} · {{ capabilitySupportLabel(item.support) }}
                          </el-tag>
                        </div>
                        <div v-if="currentModelCapabilities.metadata" class="model-metadata-grid">
                          <div v-for="item in modelMetadataRows" :key="item.label">
                            <span>{{ item.label }}</span>
                            <strong>{{ item.value }}</strong>
                          </div>
                        </div>
                        <p v-if="modelPricingLabel" class="model-pricing-note">{{ modelPricingLabel }}</p>
                        <el-alert
                          v-for="warning in modelConfigurationWarnings"
                          :key="warning"
                          class="model-capability-warning"
                          type="warning"
                          :closable="false"
                          :title="warning"
                        />
                      </div>
                    </el-form-item>

                    <div class="subsection-title">实时视觉模型</div>
                    <el-form-item label="使用独立视觉模型">
                      <el-switch v-model="form.llm.vision_enabled" @change="debouncedSave({ llm: { vision_enabled: $event } })" />
                    </el-form-item>
                    <div v-if="form.llm.vision_enabled" class="form-grid three">
                      <el-form-item label="视觉提供商">
                        <el-select v-model="form.llm.vision_provider" class="full-width" @change="debouncedSave({ llm: { vision_provider: $event } })">
                          <el-option v-for="option in llmProviderOptions" :key="option.value" :label="option.label" :value="option.value" />
                        </el-select>
                      </el-form-item>
                      <el-form-item label="视觉模型">
                        <el-input v-model="form.llm.vision_model" @change="debouncedSave({ llm: { vision_model: $event } })" />
                      </el-form-item>
                      <el-form-item label="视觉超时">
                        <el-input-number v-model="form.llm.vision_timeout" :min="5" :max="120" controls-position="right" @change="debouncedSave({ llm: { vision_timeout: $event } })" />
                      </el-form-item>
                      <el-form-item label="Vision detail">
                        <el-select v-model="form.llm.vision_detail" class="full-width" @change="debouncedSave({ llm: { vision_detail: $event } })">
                          <el-option label="Low latency" value="low" />
                          <el-option label="Auto" value="auto" />
                          <el-option label="High fidelity" value="high" />
                          <el-option label="Original" value="original" />
                        </el-select>
                      </el-form-item>
                      <el-form-item label="视觉 API 地址（OpenAI 兼容）">
                        <el-input v-model="form.llm.vision_base_url" @change="debouncedSave({ llm: { vision_base_url: $event } })" />
                      </el-form-item>
                      <el-form-item v-if="!KEYLESS_LLM_PROVIDERS.has(form.llm.vision_provider)" label="视觉 API Key">
                        <el-input v-model="form.llm.vision_api_key" type="password" show-password @change="debouncedSave({ llm: { vision_api_key: $event } })" />
                      </el-form-item>
                    </div>
                    <p v-if="form.llm.vision_enabled && (!form.llm.vision_base_url.trim() || !form.llm.vision_model.trim())" class="field-hint error">
                      视觉 API 地址和视觉模型未配置
                    </p>

                    <div class="subsection-title">{{ t('settings.llm.sectionSampling') }}</div>
                    <div class="parameter-strip">
                      <el-form-item :label="t('settings.llm.temperature', { value: form.llm.temperature.toFixed(2) })">
                        <el-slider v-model="form.llm.temperature" :min="0" :max="2" :step="0.1" @change="saveLlmField('temperature', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.topP', { value: form.llm.top_p.toFixed(2) })">
                        <el-slider v-model="form.llm.top_p" :min="0" :max="1" :step="0.05" @change="saveLlmField('top_p', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.minP', { value: form.llm.min_p.toFixed(2) })">
                        <el-slider v-model="form.llm.min_p" :min="0" :max="1" :step="0.01" @change="saveLlmField('min_p', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.frequencyPenalty', { value: form.llm.frequency_penalty.toFixed(2) })">
                        <el-slider v-model="form.llm.frequency_penalty" :min="-2" :max="2" :step="0.05" @change="saveLlmField('frequency_penalty', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.presencePenalty', { value: form.llm.presence_penalty.toFixed(2) })">
                        <el-slider v-model="form.llm.presence_penalty" :min="-2" :max="2" :step="0.05" @change="saveLlmField('presence_penalty', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.repetitionPenalty', { value: form.llm.repetition_penalty.toFixed(2) })">
                        <el-slider v-model="form.llm.repetition_penalty" :min="0" :max="2" :step="0.05" @change="saveLlmField('repetition_penalty', $event)" />
                      </el-form-item>
                    </div>

                    <div class="form-grid three">
                      <el-form-item :label="t('settings.llm.topK')">
                        <el-input-number v-model="form.llm.top_k" :min="0" :max="2000" :step="50" controls-position="right" @change="saveLlmField('top_k', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.contextTokens')">
                        <el-input-number v-model="form.llm.context_max_tokens" :min="1000" :max="2000000" :step="1000" controls-position="right" @change="saveLlmField('context_max_tokens', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.maxOutputTokens')">
                        <el-input-number v-model="form.llm.default_max_output_tokens" :min="256" :max="65535" :step="256" controls-position="right" @change="saveLlmField('default_max_output_tokens', $event)" />
                      </el-form-item>
                      <el-form-item :label="t('settings.llm.timeout')">
                        <el-input-number v-model="form.llm.timeout" :min="10" :max="300" controls-position="right" @change="saveLlmField('timeout', $event)" />
                      </el-form-item>
                    </div>
                  </div>
                </div>
              </el-form>
            </el-card>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.tts')" name="voice">
            <el-card shadow="never">
              <template #header>
                <div class="card-header">
                  <div class="header-title">
                    <span>{{ t('settings.tts.service') }}</span>
                  </div>
                  <div class="tts-toolbar">
                    <div class="tts-status-strip">
                      <el-tag :type="ttsRuntimeTagType">{{ ttsRuntimeLabel }}</el-tag>
                      <el-tag :type="hasTtsVoice ? 'success' : 'warning'">{{ hasTtsVoice ? t('common.ready') : t('settings.tts.incomplete') }}</el-tag>
                      <el-tag v-if="ttsRuntimeError" type="danger">{{ t('settings.tts.status.error') }}</el-tag>
                    </div>
                    <div class="button-row">
                      <el-button plain :loading="ttsStatusRequest.loading" @click="refreshTtsStatus">
                        <el-icon><Refresh /></el-icon>
                        {{ t('settings.tts.refreshStatus') }}
                      </el-button>
                      <el-button plain :loading="localDiscoveryRequest.loading" @click="applyLocalTtsDiscovery">
                        <el-icon><Connection /></el-icon>
                        {{ t('settings.discovery.detectLocal') }}
                      </el-button>
                      <el-button plain @click="resetCurrentTtsProfile">
                        <el-icon><Refresh /></el-icon>
                        {{ t('settings.tts.resetProfile') }}
                      </el-button>
                      <el-button type="primary" plain :loading="testTtsRequest.loading" @click="handleTestTts">
                        <el-icon><Connection /></el-icon>
                        {{ t('settings.tts.test') }}
                      </el-button>
                    </div>
                  </div>
                </div>
              </template>
              <el-form label-position="top" @submit.prevent>
                <div class="voice-main-form single">
                  <div v-if="ttsStatus || ttsStatusRequest.loading || ttsStatusRequest.error" class="tts-runtime-panel">
                    <div v-for="item in ttsRuntimeMetricItems" :key="item.label" class="tts-runtime-item">
                      <span>{{ item.label }}</span>
                      <strong>{{ item.value }}</strong>
                      <small v-if="item.detail">{{ item.detail }}</small>
                    </div>
                  </div>
                  <el-alert
                    v-if="ttsRuntimeError"
                    class="tts-runtime-alert"
                    :title="ttsRuntimeError"
                    type="error"
                    show-icon
                    :closable="false"
                  />

                  <div class="subsection-title">{{ t('settings.tts.sectionCharacter') }}</div>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.tts.character')">
                      <el-input v-model="form.tts.genie_character" @input="saveTtsField('genie_character', $event)" @change="flushTtsSave" />
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.modelDir')">
                      <el-input v-model="form.tts.genie_model_dir" @input="saveTtsField('genie_model_dir', $event)" @change="flushTtsSave" />
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.lang')">
                      <el-select v-model="form.tts.lang" class="full-width" @change="saveTtsField('lang', $event, { flush: true })">
                        <el-option :label="t('settings.tts.lang.zh')" value="zh" />
                        <el-option :label="t('settings.tts.lang.ja')" value="ja" />
                        <el-option :label="t('settings.tts.lang.en')" value="en" />
                        <el-option :label="t('common.auto')" value="auto" />
                      </el-select>
                    </el-form-item>
                  </div>

                  <div class="subsection-title">{{ t('settings.tts.sectionReference') }}</div>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.tts.referenceAudio')">
                      <el-input v-model="form.tts.ref_audio" :placeholder="t('settings.tts.referenceAudioPlaceholder')" @input="saveTtsField('ref_audio', $event)" @change="flushTtsSave" />
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.referenceText')">
                      <el-input v-model="form.tts.ref_text" type="textarea" :rows="2" :placeholder="t('settings.tts.referenceTextPlaceholder')" @input="saveTtsField('ref_text', $event)" @change="flushTtsSave" />
                    </el-form-item>
                  </div>

                  <div class="subsection-title">{{ t('settings.tts.sectionInference') }}</div>
                  <div class="form-grid three">
                    <el-form-item :label="t('settings.tts.device')">
                      <el-select v-model="form.tts.device" class="full-width" @change="saveTtsField('device', $event, { flush: true })">
                        <el-option label="CPU" value="cpu" />
                        <el-option label="CUDA" value="cuda" />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.quality')">
                      <el-select v-model="form.tts.quality" class="full-width" @change="saveTtsField('quality', $event, { flush: true })">
                        <el-option :label="t('settings.tts.quality.qualityFirst')" value="质量优先" />
                        <el-option :label="t('settings.tts.quality.speedFirst')" value="速度优先" />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.split')">
                      <el-select v-model="form.tts.split" class="full-width" @change="saveTtsField('split', $event, { flush: true })">
                        <el-option :label="t('settings.tts.split.smart')" value="智能切分" />
                        <el-option :label="t('settings.tts.split.disabled')" value="禁用" />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.mode')">
                      <el-select v-model="form.tts.mode" class="full-width" @change="saveTtsField('mode', $event, { flush: true })">
                        <el-option :label="t('settings.tts.mode.serial')" value="串行推理" />
                      </el-select>
                    </el-form-item>
                  </div>
                </div>
              </el-form>
            </el-card>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.asr')" name="asr">
            <SettingsAsrSection
              :model-value="form.asr"
              :discovery-loading="localDiscoveryRequest.loading"
              :discovery-error="localDiscoveryRequest.error"
              @discover-local="applyLocalAsrDiscovery"
              @update-field="saveAsrField"
            />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.memory')" name="memory">
            <el-card shadow="never">
              <template #header>
                <div class="card-header">
                  <span>{{ t('settings.memory.title') }}</span>
                  <div class="button-row">
                    <el-button plain :loading="localDiscoveryRequest.loading" @click="applyLocalMemoryDiscovery">
                      <el-icon><Connection /></el-icon>
                      {{ t('settings.discovery.detectLocal') }}
                    </el-button>
                    <el-button
                      type="primary"
                      plain
                      :loading="memoryRebuildRequest.loading"
                      :disabled="form.memory.backend === 'inmemory'"
                      @click="handleRebuildMemoryIndex"
                    >
                      <el-icon><Refresh /></el-icon>
                      {{ t('settings.memory.rebuildIndex') }}
                    </el-button>
                  </div>
                </div>
              </template>
              <el-form label-position="top" @submit.prevent>
                <el-form-item :label="t('settings.memory.backend')">
                  <el-radio-group v-model="form.memory.backend" @change="handleMemoryBackendChange">
                    <el-radio-button value="sqlite">SQLite</el-radio-button>
                    <el-radio-button value="inmemory">In-memory</el-radio-button>
                    <el-radio-button value="qdrant">Qdrant</el-radio-button>
                  </el-radio-group>
                </el-form-item>
                <el-form-item v-if="form.memory.backend === 'sqlite'" label="SQLite 存储文件">
                  <el-input v-model="form.memory.sqlite_path" placeholder="python/data/memory.db" @change="debouncedSave({ memory: { sqlite_path: $event } })" />
                </el-form-item>
                <el-form-item :label="t('settings.memory.embedding')">
                  <el-input v-model="form.memory.embedding_model" :placeholder="DEFAULT_EMBEDDING_MODEL" @change="debouncedSave({ memory: { embedding_model: $event } })" />
                </el-form-item>
                <el-form-item label="Learned reranker">
                  <el-switch v-model="form.memory.reranker_enabled" @change="debouncedSave({ memory: { reranker_enabled: $event } })" />
                </el-form-item>
                <div v-if="form.memory.reranker_enabled" class="form-grid">
                  <el-form-item label="Reranker model">
                    <el-input v-model="form.memory.reranker_model" @change="debouncedSave({ memory: { reranker_model: $event } })" />
                  </el-form-item>
                  <el-form-item label="Reranker candidates">
                    <el-input-number v-model="form.memory.reranker_candidate_count" :min="5" :max="100" :step="5" controls-position="right" @change="debouncedSave({ memory: { reranker_candidate_count: $event } })" />
                  </el-form-item>
                </div>
                <div v-if="form.memory.backend === 'qdrant'" class="form-grid">
                  <el-form-item :label="t('settings.memory.qdrantUrl')">
                    <el-input v-model="form.memory.qdrant_url" @change="debouncedSave({ memory: { qdrant_url: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.memory.qdrantApiKey')">
                    <el-input v-model="form.memory.qdrant_api_key" type="password" show-password @change="debouncedSave({ memory: { qdrant_api_key: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.memory.collection')">
                    <el-input v-model="form.memory.qdrant_collection" placeholder="memories" @change="debouncedSave({ memory: { qdrant_collection: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.memory.qdrantTimeout')">
                    <el-input-number v-model="form.memory.qdrant_timeout" :min="0.1" :max="300" :step="1" @change="debouncedSave({ memory: { qdrant_timeout: $event } })" />
                  </el-form-item>
                </div>
                <el-form-item v-if="form.memory.backend === 'qdrant'" :label="t('settings.memory.qdrantAutoStart')">
                  <el-switch v-model="form.memory.qdrant_auto_start" @change="debouncedSave({ memory: { qdrant_auto_start: $event } })" />
                </el-form-item>
                <div v-if="form.memory.backend === 'qdrant' && form.memory.qdrant_auto_start" class="form-grid three">
                  <el-form-item :label="t('settings.memory.qdrantDockerImage')">
                    <el-input v-model="form.memory.qdrant_docker_image" :placeholder="DEFAULT_QDRANT_DOCKER_IMAGE" @change="debouncedSave({ memory: { qdrant_docker_image: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.memory.qdrantDockerContainer')">
                    <el-input v-model="form.memory.qdrant_docker_container" placeholder="yuizaki-qdrant" @change="debouncedSave({ memory: { qdrant_docker_container: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.memory.qdrantDockerVolume')">
                    <el-input v-model="form.memory.qdrant_docker_volume" placeholder="yuizaki-qdrant-storage" @change="debouncedSave({ memory: { qdrant_docker_volume: $event } })" />
                  </el-form-item>
                </div>
              </el-form>
            </el-card>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.summary')" name="summary">
            <el-card shadow="never">
              <template #header>{{ t('settings.summary.title') }}</template>
              <el-form label-position="top" @submit.prevent>
                <div class="form-grid three">
                  <el-form-item :label="t('settings.summary.triggerMessages')">
                    <el-input-number v-model="form.summary.trigger_messages" :min="10" :max="100" controls-position="right" @change="debouncedSave({ summary: { trigger_messages: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.summary.keepRecent')">
                    <el-input-number v-model="form.summary.keep_recent_messages" :min="0" :max="50" controls-position="right" @change="debouncedSave({ summary: { keep_recent_messages: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.summary.rewriteInterval')">
                    <el-input-number v-model="form.summary.rewrite_interval_messages" :min="5" :max="100" controls-position="right" @change="debouncedSave({ summary: { rewrite_interval_messages: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.summary.itemMaxChars')">
                    <el-input-number v-model="form.summary.item_max_chars" :min="100" :max="2000" :step="100" controls-position="right" @change="debouncedSave({ summary: { item_max_chars: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.summary.scorer')">
                    <el-select v-model="form.summary.quality_scorer_mode" class="full-width" @change="debouncedSave({ summary: { quality_scorer_mode: $event } })">
                      <el-option label="Rule" value="rule" />
                      <el-option label="LLM" value="llm" />
                    </el-select>
                  </el-form-item>
                  <el-form-item :label="t('settings.summary.budget')">
                    <el-input-number v-model="form.summary.quality_score_budget_per_hour" :min="1" :max="100" controls-position="right" @change="debouncedSave({ summary: { quality_score_budget_per_hour: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.summary.cooldown')">
                    <el-input-number v-model="form.summary.quality_score_cooldown_seconds" :min="0" :max="3600" :step="60" controls-position="right" @change="debouncedSave({ summary: { quality_score_cooldown_seconds: $event } })" />
                  </el-form-item>
                </div>
              </el-form>
            </el-card>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.svc')" name="svc">
            <el-card shadow="never">
              <template #header>
                <div class="card-header">
                  <span>{{ t('settings.svc.service') }}</span>
                  <div class="button-row">
                    <el-button plain :loading="localDiscoveryRequest.loading" @click="applyLocalSvcDiscovery">
                      <el-icon><Connection /></el-icon>
                      {{ t('settings.discovery.detectLocal') }}
                    </el-button>
                    <el-tag :type="hasSvcEndpoint ? 'success' : 'info'">{{ hasSvcEndpoint ? t('common.configured') : t('common.optional') }}</el-tag>
                  </div>
                </div>
              </template>
              <el-form label-position="top" @submit.prevent>
                <el-form-item :label="t('settings.svc.provider')">
                  <el-select v-model="form.svc.provider" class="full-width" @change="debouncedSave({ svc: { provider: $event } })">
                    <el-option label="SoulX-Singer-SVC Service" value="soulx-service" />
                    <el-option :label="t('common.disabled')" value="disabled" />
                  </el-select>
                </el-form-item>
                <el-form-item :label="t('settings.svc.baseUrl')">
                  <el-input v-model="form.svc.base_url" @change="debouncedSave({ svc: { base_url: $event } })" />
                </el-form-item>
                <div class="form-grid">
                  <el-form-item :label="t('settings.svc.referenceAudioId')">
                    <el-input-number v-model="form.svc.speaker_id" :min="0" controls-position="right" @change="debouncedSave({ svc: { speaker_id: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.svc.pitch')">
                    <el-input-number v-model="form.svc.pitch" :min="-36" :max="36" controls-position="right" @change="debouncedSave({ svc: { pitch: $event } })" />
                  </el-form-item>
                  <el-form-item :label="t('settings.svc.timeout')">
                    <el-input-number v-model="form.svc.timeout" :min="10" :max="900" controls-position="right" @change="debouncedSave({ svc: { timeout: $event } })" />
                  </el-form-item>
                </div>
              </el-form>
            </el-card>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.resources')" name="resources">
            <div class="resource-stack">
              <el-alert
                v-if="resourceMessage"
                :title="resourceMessage"
                :type="resourceMessageType"
                show-icon
                :closable="false"
              />

              <div class="button-row">
                <el-button plain :loading="resourceLoading || storageLoading" @click="refreshResourcePanel">{{ t('settings.resource.refresh') }}</el-button>
                <el-button
                  v-if="cancellableResourceIds.length > 0"
                  type="danger"
                  plain
                  :icon="CircleClose"
                  :loading="resourceCancelLoading"
                  @click="cancelActiveResourceDownloads"
                >取消下载</el-button>
              </div>

              <div v-if="activeDownloadProgress.length" class="resource-progress-list" aria-live="polite">
                <div v-for="progress in activeDownloadProgress" :key="progress.resourceId" class="resource-progress-row">
                  <div class="resource-progress-header">
                    <strong>{{ resourceProgressLabel(progress.resourceId) }}</strong>
                    <span>{{ resourceProgressPhaseLabel(progress.phase) }}</span>
                  </div>
                  <el-progress
                    :percentage="progress.percent ?? 100"
                    :indeterminate="progress.percent === null"
                    :show-text="progress.percent !== null"
                    :stroke-width="8"
                  />
                  <span v-if="progress.bytesDownloaded !== null" class="resource-progress-bytes">
                    {{ formatStorageBytes(progress.bytesDownloaded) }}<template v-if="progress.bytesTotal !== null"> / {{ formatStorageBytes(progress.bytesTotal) }}</template>
                  </span>
                </div>
              </div>

              <div v-if="resourceView" class="resource-download-bar">
                <el-checkbox-group v-model="selectedResourceIds" class="resource-download-options">
                  <el-checkbox
                    v-for="item in resourceDownloadOptions"
                    :key="item.id"
                    :value="item.id"
                    :disabled="item.ready"
                  >
                    <span class="resource-download-label">{{ item.label }}</span>
                    <el-tag size="small" type="info">{{ item.version }}</el-tag>
                    <span>{{ formatResourceDownloadBytes(item.downloadBytes) }}</span>
                    <span>{{ item.license }}</span>
                    <el-tag v-if="item.resumable" size="small" type="warning">
                      可续传 {{ formatStorageBytes(item.resumable.bytesDownloaded) }}<template v-if="item.resumable.bytesTotal !== null"> / {{ formatStorageBytes(item.resumable.bytesTotal) }}</template>
                    </el-tag>
                  </el-checkbox>
                </el-checkbox-group>
                <el-button
                  type="primary"
                  :icon="Download"
                  :loading="resourceActionLoading('selected-download')"
                  :disabled="selectedResourceIds.length === 0"
                  @click="downloadSelectedResources"
                >
                  下载选中项
                </el-button>
              </div>

              <section v-if="storageStatus" class="storage-maintenance" aria-labelledby="storage-maintenance-title">
                <div class="storage-maintenance-header">
                  <strong id="storage-maintenance-title">{{ t('settings.storage.title') }}</strong>
                  <div class="storage-summary">
                    <el-tag type="info">{{ formatStorageBytes(storageStatus.total_bytes) }}</el-tag>
                    <el-button
                      type="danger"
                      plain
                      :icon="Delete"
                      :loading="storageActionKey === 'all'"
                      :disabled="storageStatus.reclaimable_bytes <= 0"
                      @click="cleanupAllStorage"
                    >
                      {{ t('settings.storage.cleanAll') }}
                    </el-button>
                  </div>
                </div>
                <el-table :data="storageStatus.categories" size="small" class="storage-table">
                  <el-table-column :label="t('settings.storage.category')" min-width="150">
                    <template #default="scope">
                      <template v-if="scope.row">{{ storageCategoryLabel(scope.row.id) }}</template>
                    </template>
                  </el-table-column>
                  <el-table-column prop="files" :label="t('settings.storage.files')" width="88" />
                  <el-table-column :label="t('settings.storage.size')" width="110">
                    <template #default="scope">
                      <template v-if="scope.row">{{ formatStorageBytes(scope.row.bytes) }}</template>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('settings.storage.persistence')" width="110">
                    <template #default="scope">
                      <el-tag v-if="scope.row" size="small" type="info">{{ scope.row.persistence === 'memory_only' ? t('settings.storage.memoryOnly') : t('settings.storage.disk') }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('settings.storage.action')" width="150" align="right">
                    <template #default="scope">
                      <el-button
                        v-if="scope.row?.action === 'delete_files'"
                        type="danger"
                        plain
                        size="small"
                        :icon="Delete"
                        :loading="storageActionKey === scope.row.id"
                        :disabled="scope.row.files <= 0"
                        @click="cleanupStorage([scope.row.id])"
                      >
                        {{ t('settings.storage.permanentClean') }}
                      </el-button>
                      <el-button
                        v-else-if="scope.row?.action === 'compact'"
                        plain
                        size="small"
                        :icon="Refresh"
                        :loading="storageActionKey === scope.row.id"
                        @click="cleanupStorage([scope.row.id])"
                      >
                        {{ t('settings.storage.compact') }}
                      </el-button>
                      <span v-else-if="scope.row" class="storage-no-action">{{ t('settings.storage.none') }}</span>
                    </template>
                  </el-table-column>
                </el-table>
              </section>

              <div v-if="resourceView" class="resource-grid">
                <el-card class="resource-card" shadow="never">
                  <template #header>
                    <div class="card-header">
                      <span>{{ t('settings.resource.desktopLibrary') }}</span>
                      <el-tag type="info">{{ resourceView.localCounts.live2d }} Live2D / {{ resourceView.localCounts.vrm }} VRM</el-tag>
                    </div>
                  </template>
                  <div class="resource-details">
                    <div>
                      <strong>{{ t('settings.resource.live2dRoot') }}</strong>
                      <code class="resource-path">{{ resourceView.modelRoots.live2d }}</code>
                    </div>
                    <div>
                      <strong>{{ t('settings.resource.vrmRoot') }}</strong>
                      <code class="resource-path">{{ resourceView.modelRoots.vrm }}</code>
                    </div>
                  </div>
                </el-card>

                <el-card class="resource-card" shadow="never">
                  <template #header>
                    <div class="card-header">
                      <span>Sherpa Streaming Zipformer2 CTC</span>
                      <el-tag :type="resourceTagType(resourceView.sherpaOnline.state)">{{ resourceView.sherpaOnline.message }}</el-tag>
                    </div>
                  </template>
                  <div class="resource-details">
                    <div>
                      <strong>{{ t('settings.resource.model') }}</strong>
                      <code class="resource-path">{{ resourceView.sherpaOnline.modelPath }}</code>
                    </div>
                    <div>
                      <strong>Sherpa Tokens</strong>
                      <code class="resource-path">{{ resourceView.sherpaOnline.tokensPath }}</code>
                    </div>
                    <div>
                      <strong>Runtime validation</strong>
                      <el-tag :type="resourceView.sherpaOnline.validated ? 'success' : 'warning'">
                        {{ resourceView.sherpaOnline.validated ? 'Zipformer2 CTC verified' : 'Not verified' }}
                      </el-tag>
                    </div>
                  </div>
                  <ul v-if="resourceView.sherpaOnline.details.length" class="resource-list">
                    <li v-for="detail in resourceView.sherpaOnline.details" :key="detail">{{ detail }}</li>
                  </ul>
                  <div class="button-row resource-actions">
                    <el-button
                      type="primary"
                      plain
                      :loading="resourceActionLoading('sherpa-online-download')"
                      @click="runResourceCommand('sherpa-online-download', () => resourceClient.prepareSherpaOnline(), ['sherpa_online'])"
                    >
                      {{ t('settings.resource.downloadSherpa') }} (Streaming)
                    </el-button>
                    <el-button
                      v-if="resourceView.sherpaOnline.state !== 'missing'"
                      type="danger"
                      plain
                      :icon="Delete"
                      :loading="resourceActionLoading('remove-sherpa_online')"
                      @click="removeModelResource('sherpa_online', '流式语音识别', resourceView.sherpaOnline.metadata)"
                    >永久卸载</el-button>
                  </div>
                </el-card>

                <el-card class="resource-card" shadow="never">
                  <template #header>
                    <div class="card-header">
                      <span>SoulX-Singer-SVC</span>
                      <el-tag :type="resourceTagType(resourceView.soulx.state)">{{ resourceView.soulx.message }}</el-tag>
                    </div>
                  </template>
                  <div class="resource-details">
                    <div>
                      <strong>{{ t('settings.resource.checkpoint') }}</strong>
                      <code class="resource-path">{{ resourceView.soulx.checkpointPath || resourceView.soulx.checkpointCandidates[0] }}</code>
                    </div>
                    <div>
                      <strong>{{ t('settings.resource.preprocessDir') }}</strong>
                      <code class="resource-path">{{ resourceView.soulx.preprocessDir }}</code>
                    </div>
                    <div>
                      <strong>{{ t('settings.resource.referenceDir') }}</strong>
                      <code class="resource-path">{{ resourceView.soulx.referenceDir }}</code>
                    </div>
                    <div>
                      <strong>参考音频</strong>
                      <el-tag :type="resourceView.soulx.hasReferenceAudio ? 'success' : 'info'">
                        {{ resourceView.soulx.hasReferenceAudio ? '已导入' : '未导入' }}
                      </el-tag>
                    </div>
                  </div>
                  <ul v-if="resourceView.soulx.details.length" class="resource-list">
                    <li v-for="detail in resourceView.soulx.details" :key="detail">{{ detail }}</li>
                  </ul>
                  <div class="button-row resource-actions">
                    <el-button
                      type="primary"
                      plain
                      :loading="resourceActionLoading('soulx-download')"
                      @click="runResourceCommand('soulx-download', () => resourceClient.prepareSoulx(), ['soulx'])"
                    >
                      {{ t('settings.resource.downloadSoulx') }}
                    </el-button>
                    <el-button
                      plain
                      :loading="resourceActionLoading('soulx-reference')"
                      @click="runResourceCommand('soulx-reference', () => resourceClient.importSoulxReference())"
                    >
                      {{ t('settings.resource.importReference') }}
                    </el-button>
                    <el-button
                      v-if="resourceView.soulx.state !== 'missing'"
                      type="danger"
                      plain
                      :icon="Delete"
                      :loading="resourceActionLoading('remove-soulx')"
                      @click="removeModelResource('soulx', 'SoulX 变声', resourceView.soulx.metadata)"
                    >永久卸载</el-button>
                  </div>
                </el-card>

                <el-card class="resource-card" shadow="never">
                  <template #header>
                    <div class="card-header">
                      <span>Sherpa SenseVoice</span>
                      <el-tag :type="resourceTagType(resourceView.sherpa.state)">{{ resourceView.sherpa.message }}</el-tag>
                    </div>
                  </template>
                  <div class="resource-details">
                    <div>
                      <strong>{{ t('settings.resource.model') }}</strong>
                      <code class="resource-path">{{ resourceView.sherpa.modelPath }}</code>
                    </div>
                    <div>
                      <strong>Sherpa Tokens</strong>
                      <code class="resource-path">{{ resourceView.sherpa.tokensPath }}</code>
                    </div>
                  </div>
                  <ul v-if="resourceView.sherpa.details.length" class="resource-list">
                    <li v-for="detail in resourceView.sherpa.details" :key="detail">{{ detail }}</li>
                  </ul>
                  <div class="button-row resource-actions">
                    <el-button
                      type="primary"
                      plain
                      :loading="resourceActionLoading('sherpa-download')"
                      @click="runResourceCommand('sherpa-download', () => resourceClient.prepareSherpa(), ['sherpa'])"
                    >
                      {{ t('settings.resource.downloadSherpa') }}
                    </el-button>
                    <el-button
                      v-if="resourceView.sherpa.state !== 'missing'"
                      type="danger"
                      plain
                      :icon="Delete"
                      :loading="resourceActionLoading('remove-sherpa')"
                      @click="removeModelResource('sherpa', '离线语音识别', resourceView.sherpa.metadata)"
                    >永久卸载</el-button>
                  </div>
                </el-card>

                <el-card class="resource-card" shadow="never">
                  <template #header>
                    <div class="card-header">
                      <span>{{ t('settings.resource.embedding') }}</span>
                      <el-tag :type="resourceTagType(resourceView.embedding.state)">{{ resourceView.embedding.message }}</el-tag>
                    </div>
                  </template>
                  <div class="resource-details">
                    <div>
                      <strong>{{ t('settings.resource.model') }}</strong>
                      <code class="resource-path">{{ resourceView.embedding.modelName }}</code>
                    </div>
                    <div>
                      <strong>{{ t('settings.resource.snapshot') }}</strong>
                      <code class="resource-path">{{ resourceView.embedding.cachePath || resourceView.embedding.cacheRoot }}</code>
                    </div>
                  </div>
                  <ul v-if="resourceView.embedding.details.length" class="resource-list">
                    <li v-for="detail in resourceView.embedding.details" :key="detail">{{ detail }}</li>
                  </ul>
                  <div class="button-row resource-actions">
                    <el-button
                      type="primary"
                      plain
                      :loading="resourceActionLoading('embedding-prefetch')"
                      @click="runResourceCommand('embedding-prefetch', () => resourceClient.prepareEmbedding(), ['embedding'])"
                    >
                      {{ t('settings.resource.prefetchEmbedding') }}
                    </el-button>
                    <el-button
                      v-if="resourceView.embedding.state !== 'missing'"
                      type="danger"
                      plain
                      :icon="Delete"
                      :loading="resourceActionLoading('remove-embedding')"
                      @click="removeModelResource('embedding', '长期记忆嵌入', resourceView.embedding.metadata)"
                    >永久卸载</el-button>
                  </div>
                </el-card>

                <el-card class="resource-card" shadow="never">
                  <template #header>
                    <div class="card-header">
                      <span>{{ t('settings.resource.ttsAssets') }}</span>
                      <el-tag :type="resourceTagType(resourceView.tts.state)">{{ resourceView.tts.message }}</el-tag>
                    </div>
                  </template>
                  <div class="resource-details">
                    <div>
                      <strong>{{ t('settings.resource.character') }}</strong>
                      <code class="resource-path">{{ resourceView.tts.character }}</code>
                    </div>
                    <div>
                      <strong>{{ t('settings.resource.cacheDir') }}</strong>
                      <code class="resource-path">{{ resourceView.tts.cacheDir }}</code>
                    </div>
                    <div>
                      <strong>{{ t('settings.resource.modelDir') }}</strong>
                      <code class="resource-path">{{ resourceView.tts.modelDir }}</code>
                    </div>
                  </div>
                  <ul v-if="resourceView.tts.details.length" class="resource-list">
                    <li v-for="detail in resourceView.tts.details" :key="detail">{{ detail }}</li>
                  </ul>
                  <div class="button-row resource-actions">
                    <el-button
                      type="primary"
                      plain
                      :loading="resourceActionLoading('tts-prefetch')"
                      @click="runResourceCommand('tts-prefetch', () => resourceClient.prepareTts(), ['tts'])"
                    >
                      {{ t('settings.resource.prefetchTts') }}
                    </el-button>
                    <el-button
                      v-if="resourceView.tts.state !== 'missing'"
                      type="danger"
                      plain
                      :icon="Delete"
                      :loading="resourceActionLoading('remove-tts')"
                      @click="removeModelResource('tts', 'Genie TTS', resourceView.tts.metadata)"
                    >永久卸载</el-button>
                  </div>
                </el-card>
              </div>

              <el-empty v-else :description="t('settings.resource.noStatus')" />
            </div>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.system')" name="system">
            <el-card shadow="never">
              <template #header>{{ t('settings.interface.title') }}</template>
              <el-form label-position="top" @submit.prevent>
                <el-form-item :label="t('settings.system.theme')">
                  <el-segmented v-model="form.system.theme" :options="themeOptions" @change="handleSystemThemeChange" />
                </el-form-item>
                <el-form-item :label="t('settings.system.language')">
                  <el-segmented v-model="form.system.language" :options="languageOptions" @change="handleSystemLanguageChange" />
                </el-form-item>
              </el-form>
            </el-card>

            <el-card class="desktop-input-card" shadow="never">
              <template #header>
                <div class="card-header">
                  <div class="header-title">
                    <span>桌面输入</span>
                  </div>
                  <div class="button-row">
                    <el-tag :type="inputBindingState.status.pushToTalkActive ? 'success' : 'warning'">
                      {{ inputBindingState.status.pushToTalkActive ? '侧键监听可用' : '侧键监听不可用' }}
                    </el-tag>
                    <el-button :icon="Refresh" :loading="inputBindingState.loading" title="恢复默认快捷键" aria-label="恢复默认快捷键" @click="resetDesktopInputBindings" />
                  </div>
                </div>
              </template>

              <el-alert
                v-if="!inputBindingState.available"
                type="info"
                :closable="false"
                title="桌面输入配置仅在 Electron 应用中可用"
              />
              <el-alert
                v-else-if="inputBindingState.status.errors.length"
                type="warning"
                :closable="false"
                :title="inputBindingState.status.errors.join('；')"
              />

              <el-form class="desktop-input-form" label-position="top" @submit.prevent>
                <div class="desktop-input-row">
                  <div>
                    <strong>按住说话</strong>
                  </div>
                  <el-switch
                    :model-value="inputBindingState.settings.pushToTalk.enabled"
                    :disabled="!inputBindingState.available || inputBindingState.loading"
                    @change="setPushToTalkEnabled"
                  />
                  <el-select
                    :model-value="inputBindingState.settings.pushToTalk.mouseButton"
                    :disabled="!inputBindingState.available || inputBindingState.loading"
                    class="desktop-input-select"
                    @change="setPushToTalkMouseButton"
                  >
                    <el-option label="鼠标侧键 1（后退）" :value="4" />
                    <el-option label="鼠标侧键 2（前进）" :value="5" />
                  </el-select>
                </div>

                <div class="keyboard-binding-list">
                  <div v-for="binding in keyboardBindingRows" :key="binding.action" class="keyboard-binding-row">
                    <div>
                      <strong>{{ binding.label }}</strong>
                    </div>
                    <el-input
                      :model-value="inputBindingState.settings.keyboard[binding.action]"
                      :placeholder="activeKeyboardCapture === binding.action ? '请按下组合键' : '点击后按下组合键'"
                      :disabled="!inputBindingState.available || inputBindingState.loading"
                      readonly
                      @focus="activeKeyboardCapture = binding.action"
                      @blur="activeKeyboardCapture = null"
                      @keydown.prevent="captureKeyboardBinding(binding.action, $event)"
                    >
                      <template #append>
                        <el-button
                          :icon="CircleClose"
                          :disabled="!inputBindingState.settings.keyboard[binding.action]"
                          title="禁用此快捷键"
                          :aria-label="`禁用${binding.label}`"
                          @mousedown.prevent
                          @click="clearKeyboardBinding(binding.action)"
                        />
                      </template>
                    </el-input>
                    <el-tag :type="inputBindingState.status.keyboard[binding.action] ? 'success' : 'info'">
                      {{ inputBindingState.status.keyboard[binding.action] ? '已注册' : inputBindingState.settings.keyboard[binding.action] ? '不可用' : '已禁用' }}
                    </el-tag>
                  </div>
                </div>
              </el-form>
            </el-card>

            <el-card class="settings-admin-card" shadow="never">
              <template #header>{{ t('settings.admin.title') }}</template>
              <el-collapse>
                <el-collapse-item :title="t('settings.admin.editor')" name="metadata">
                  <div class="button-row">
                    <el-button plain @click="loadSettingsAdmin">{{ t('settings.admin.metadata') }}</el-button>
                    <el-button plain type="warning" @click="clearSettingsHistory">{{ t('settings.admin.clearHistory') }}</el-button>
                  </div>
                  <pre class="settings-json">{{ JSON.stringify(settingsMetadata, null, 2) }}</pre>
                  <el-table :data="settingsHistory" size="small" height="220">
                    <el-table-column type="index" width="52" />
                    <el-table-column :label="t('settings.admin.details')">
                      <template #default="scope">
                        <pre class="table-json">{{ JSON.stringify(scope.row, null, 2) }}</pre>
                      </template>
                    </el-table-column>
                  </el-table>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.key.rollbackSteps')">
                      <el-input-number v-model="rollbackSteps" :min="1" :max="20" controls-position="right" />
                    </el-form-item>
                    <el-form-item :label="t('settings.key.delete')">
                      <el-input v-model="deleteKey" placeholder="llm.model / tts.lang" />
                    </el-form-item>
                  </div>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.key.lookup')">
                      <el-input v-model="lookupKey" placeholder="summary.trigger_messages" />
                    </el-form-item>
                    <el-form-item :label="t('settings.key.write')">
                      <el-input v-model="setKey" placeholder="system.theme" />
                    </el-form-item>
                  </div>
                  <el-form-item :label="t('settings.key.valueJson')">
                    <el-input v-model="setValueJson" type="textarea" :rows="2" placeholder='"dark" / 42 / {"enabled":true}' />
                  </el-form-item>
                  <pre v-if="lookupResult" class="settings-json">{{ lookupResult }}</pre>
                  <div class="button-row">
                    <el-button type="warning" plain @click="rollbackSettings">{{ t('common.rollback') }}</el-button>
                    <el-button plain :disabled="!lookupKey.trim()" @click="readSettingKey">{{ t('common.read') }}</el-button>
                    <el-button type="primary" plain :disabled="!setKey.trim() || !setValueJson.trim()" @click="writeSettingKey">{{ t('common.write') }}</el-button>
                    <el-button type="danger" plain :disabled="!deleteKey.trim()" @click="resetSettingKey">{{ t('common.delete') }}</el-button>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </el-card>
          </el-tab-pane>
        </el-tabs>
      </div>
    </AsyncState>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleClose, Connection, Delete, Document, Download, Refresh, Upload } from '@element-plus/icons-vue'
import { currentLocale, localeLabel, normalizeLocale, setLocale, supportedLocales, t } from '@/i18n'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { useDomainRequest } from '@/shared/composables/useDomainRequest'
import { useSettingsStore } from '@/state/settingsStore'
import {
  DEFAULT_LLM_CONTEXT_MAX_TOKENS,
  DEFAULT_LLM_MAX_OUTPUT_TOKENS,
  DEFAULT_QDRANT_DOCKER_IMAGE,
} from '@/../shared/runtime-defaults'
import { useInputBindingsStore } from '@/state/inputBindingsStore'
import { settingsClient, type BackendTokenMutationResponse, type BackendTokenStatusResponse, type LocalRuntimeCandidate, type LocalRuntimeDiscoveryResponse, type TtsRuntimeStatusResponse } from '@/api/clients/settings-client'
import { resourceClient } from '@/api/clients/resource-client'
import { memoryClient } from '@/api/clients/memory-client'
import type { ManagedModelResourceId, ManagedResourceMetadata, ModelResourceStatusPayload, ResumableResourceDownload, ResourceCommandResult, ResourceDownloadProgress, ResourceProgressPhase, StorageCategoryId, StorageStatusPayload } from '@/../shared/resource-manager'
import { DEFAULT_VAD_MIN_SILENCE_MS } from '@/../shared/runtime-defaults'
import { inferModelCapabilities, type ModelCapabilitySupport } from '@/../shared/model-capabilities'
import type { InputBindingSettingsPatch, KeyboardShortcutAction, MouseSideButton } from '@/../shared/input-bindings'
import { useSettingsDomain } from '../composables/useSettingsDomain'
import SettingsAsrSection, { type AsrSettings } from '../components/SettingsAsrSection.vue'
import { isLocalLlmEndpoint, normalizeOpenAiBaseUrl, shouldAutoDiscoverLlmModels } from '../llmDiscovery'
import { LLM_PROVIDER_BASE_URLS, LLM_PROVIDER_ENDPOINTS, choosePreferredLlmModel, getLlmProviderOptions, inferLlmProviderPreset } from '../llmProviders'
import type { LlmProviderPreset } from '../llmProviders'

type SaveTimeout = ReturnType<typeof window.setTimeout>
type SettingSectionId = 'llm' | 'voice' | 'asr' | 'memory' | 'summary' | 'svc' | 'resources' | 'system'
type QualityScorerMode = 'rule' | 'llm'
type SettingsPatch = Record<string, unknown>
type AlertType = 'success' | 'warning' | 'info' | 'error'
type StorageCleanupTarget = Exclude<StorageCategoryId, 'visual_frames'>
const DEFAULT_EMBEDDING_MODEL = 'Qwen/Qwen3-Embedding-0.6B'
type LlmModelDiscoveryOptions = {
  forceAutoSelect?: boolean
  manual?: boolean
}
type LlmProfile = {
  provider: LlmProviderPreset
  base_url: string
  api_key: string
  model: string
  temperature: number
  top_p: number
  top_k: number
  min_p: number
  frequency_penalty: number
  presence_penalty: number
  repetition_penalty: number
  timeout: number
  context_max_tokens: number
  default_max_output_tokens: number
}
type LlmProfileField = keyof LlmProfile
type LlmProfiles = Partial<Record<LlmProviderPreset, LlmProfile>>
type ProviderStatusClass = 'ready' | 'warning' | 'muted'
type TtsProviderPreset = 'genie-tts'
type SaveFieldOptions = {
  flush?: boolean
}
type TagType = 'success' | 'warning' | 'info' | 'danger'
type TtsProfile = {
  genie_character: string
  genie_model_dir: string
  ref_audio: string
  ref_text: string
  lang: string
  device: 'cpu' | 'cuda'
  quality: string
  split: string
  mode: string
  save_mode: string
  provider: TtsProviderPreset
}
type TtsProfileField = keyof TtsProfile

const KEYLESS_LLM_PROVIDERS = new Set<LlmProviderPreset>(['ollama', 'lmstudio'])
const llmProfileNeedsApiKey = (profile: Pick<LlmProfile, 'provider' | 'base_url'>): boolean => {
  return !KEYLESS_LLM_PROVIDERS.has(profile.provider) && !isLocalLlmEndpoint(normalizeOpenAiBaseUrl(profile.base_url))
}
const TTS_PROVIDER: TtsProviderPreset = 'genie-tts'

const {
  settings,
  settingsRequest,
  updateRequest,
  llmModels,
  llmModelsRequest,
  ttsStatus,
  ttsStatusRequest,
  testLlmRequest,
  testTtsRequest,
  loadSettings,
  patchSettings,
  loadLlmModels,
  loadTtsStatus,
  testLlm,
  testTts,
  warmupTtsRequest,
  warmupTts,
} = useSettingsDomain()

const settingsStore = useSettingsStore()
const inputBindingsStore = useInputBindingsStore()
const inputBindingState = inputBindingsStore.state
const activeKeyboardCapture = ref<KeyboardShortcutAction | null>(null)
const keyboardBindingRows: Array<{
  action: KeyboardShortcutAction
  label: string
}> = [
  { action: 'interact', label: '切换拖动模式' },
  { action: 'lock', label: '锁定桌宠位置' },
  { action: 'openPanel', label: '打开陪伴面板' },
  { action: 'toggleVision', label: '暂停或恢复视觉' },
]

const form = reactive({
  llm: {
    provider: 'custom' as LlmProviderPreset,
    base_url: '',
    api_key: '',
    model: '',
    temperature: 1.2,
    top_p: 0.9,
    top_k: 500,
    min_p: 0,
    frequency_penalty: 0.2,
    presence_penalty: 0,
    repetition_penalty: 1,
    timeout: 60,
    context_max_tokens: DEFAULT_LLM_CONTEXT_MAX_TOKENS,
    default_max_output_tokens: DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    vision_enabled: false,
    vision_provider: 'custom' as LlmProviderPreset,
    vision_base_url: '',
    vision_api_key: '',
    vision_model: '',
    vision_timeout: 30,
    vision_detail: 'low' as 'low' | 'high' | 'auto' | 'original',
  },
  tts: {
    genie_character: '',
    genie_model_dir: '',
    ref_audio: '',
    ref_text: '',
    lang: 'ja',
    device: 'cpu',
    quality: '质量优先',
    split: '智能切分',
    mode: '串行推理',
    save_mode: '禁用自动保存',
    provider: TTS_PROVIDER,
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
  summary: {
    trigger_messages: 24,
    keep_recent_messages: 8,
    item_max_chars: 140,
    rewrite_interval_messages: 6,
    quality_scorer_mode: 'rule' as QualityScorerMode,
    quality_score_cooldown_seconds: 300,
    quality_score_budget_per_hour: 20,
  },
  memory: {
    backend: 'sqlite',
    sqlite_path: '',
    qdrant_url: '',
    qdrant_api_key: '',
    qdrant_collection: 'memories',
    qdrant_timeout: 10,
    qdrant_auto_start: true,
    qdrant_docker_image: DEFAULT_QDRANT_DOCKER_IMAGE,
    qdrant_docker_container: 'yuizaki-qdrant',
    qdrant_docker_volume: 'yuizaki-qdrant-storage',
    embedding_model: DEFAULT_EMBEDDING_MODEL,
    reranker_enabled: false,
    reranker_model: 'BAAI/bge-reranker-v2-m3',
    reranker_candidate_count: 32,
  },
  system: {
    language: 'zh-CN',
    theme: 'light',
  },
})

const activeSection = ref<SettingSectionId>('llm')
const lastSavedAt = ref('')
const lastApplied = ref<string[]>([])
let saveTimeout: SaveTimeout | null = null
let modelDiscoveryTimeout: SaveTimeout | null = null
let modelDiscoveryRun = 0
let suppressModelDiscovery = false
const pendingSavePatch = ref<SettingsPatch | null>(null)
const failedSavePatch = ref<SettingsPatch | null>(null)
const saveInFlight = ref(false)
let saveFailureCount = 0
let unmounted = false
let saveIdleResolvers: Array<(value: boolean) => void> = []
const settingsMetadata = ref<Record<string, unknown> | null>(null)
const settingsHistory = ref<unknown[]>([])
const memoryRebuildRequest = useDomainRequest<Record<string, unknown>>()
const rollbackSteps = ref(1)
const deleteKey = ref('')
const lookupKey = ref('')
const lookupResult = ref('')
const setKey = ref('')
const setValueJson = ref('')
const llmModelStatus = ref('')
const llmModelAutoSelected = ref(false)
const adminTokenInput = ref('')
const adminTokenConfigured = ref(false)
const adminTokenRequest = useDomainRequest<{ ok?: boolean; hasToken: boolean }>()
const backendTokenInput = ref('')
const backendTokenStatus = ref<BackendTokenStatusResponse | null>(null)
const backendTokenStatusRequest = useDomainRequest<BackendTokenStatusResponse>()
const backendTokenMutationRequest = useDomainRequest<BackendTokenMutationResponse>()
const localDiscoveryRequest = useDomainRequest<LocalRuntimeDiscoveryResponse>()
const llmProviderPreset = ref<LlmProviderPreset>('custom')
const llmProfiles = reactive<LlmProfiles>({})
const llmImportInput = ref<HTMLInputElement | null>(null)
const llmImporting = ref(false)
const llmExporting = ref(false)
const resourceStatus = ref<ModelResourceStatusPayload | null>(null)
const resourceLoading = ref(false)
const resourceActionKey = ref('')
const resourceMessage = ref('')
const resourceMessageType = ref<AlertType>('info')
const selectedResourceIds = ref<ManagedModelResourceId[]>([])
const activeResourceIds = ref<ManagedModelResourceId[]>([])
const resourceCancelLoading = ref(false)
let resourceProgressPollTimer: ReturnType<typeof window.setInterval> | null = null
let resourceProgressPollBusy = false
const storageStatus = ref<StorageStatusPayload | null>(null)
const storageLoading = ref(false)
const storageActionKey = ref('')

const llmProviderOptions = computed(() => getLlmProviderOptions(t('common.custom')))
const activeLlmProfileLabel = computed(() => (
  llmProviderOptions.value.find((item) => item.value === llmProviderPreset.value)?.label || t('common.custom')
))
const llmProviderNeedsApiKey = computed(() => llmProfileNeedsApiKey({
  provider: llmProviderPreset.value,
  base_url: form.llm.base_url,
}))
const llmApiKeyTagLabel = computed(() => {
  if (!llmProviderNeedsApiKey.value) return t('settings.llm.apiKeyNotRequired')
  return form.llm.api_key.trim() ? t('settings.llm.apiKeySavedTag') : t('settings.llm.apiKeyMissing')
})

const saveAsrField = (field: keyof AsrSettings, value: string | number) => {
  Object.assign(form.asr, { [field]: value })
  debouncedSave({ asr: { [field]: value } })
}
const activeTtsProviderLabel = computed(() => t('settings.tts.genieProvider'))
const formatTtsDuration = (value?: number | null): string => {
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue)) return t('settings.tts.metric.empty')
  if (numericValue >= 1000) {
    const seconds = numericValue / 1000
    return `${seconds.toFixed(seconds >= 10 ? 1 : 2)}s`
  }
  return `${Math.max(0, Math.round(numericValue))}ms`
}
const formatTtsLatencySummary = (summary?: { samples: number; p50_ms?: number | null; p95_ms?: number | null }): string => {
  if (!summary?.samples) return ''
  return `P50 ${formatTtsDuration(summary.p50_ms)} · P95 ${formatTtsDuration(summary.p95_ms)} · n=${summary.samples}`
}
const ttsRuntimeError = computed(() => ttsStatusRequest.error || ttsStatus.value?.last_error || '')
const ttsRuntimeLabel = computed(() => {
  const snapshot = ttsStatus.value
  if (ttsStatusRequest.loading) return t('settings.tts.status.refreshing')
  if (ttsStatusRequest.error) return t('settings.tts.status.unreadable')
  if (!snapshot) return t('settings.tts.status.unread')
  if (snapshot.loading) return t('settings.tts.status.loading')
  if (snapshot.warmup_running || snapshot.warming_up) return t('settings.tts.status.warming')
  if (snapshot.inference_running) return t('settings.tts.status.synthesizing')
  if (snapshot.warmup_done) return t('settings.tts.status.ready')
  if (snapshot.available) return t('settings.tts.status.loaded')
  return t('settings.tts.status.cold')
})
const ttsRuntimeTagType = computed<TagType>(() => {
  const snapshot = ttsStatus.value
  if (ttsStatusRequest.error || snapshot?.last_error) return 'danger'
  if (ttsStatusRequest.loading || snapshot?.loading || snapshot?.warmup_running || snapshot?.warming_up || snapshot?.inference_running) return 'warning'
  if (snapshot?.warmup_done || snapshot?.available) return 'success'
  return 'info'
})
const ttsRuntimeMetricItems = computed(() => {
  const snapshot: TtsRuntimeStatusResponse | null = ttsStatus.value
  const capabilities = snapshot?.capabilities
  const transportMode = capabilities?.output_transport === 'unavailable'
    ? undefined
    : capabilities?.output_transport || snapshot?.streaming_transport
  const transport = transportMode === 'pcm_s16le'
    ? t('settings.tts.transport.pcm')
    : transportMode === 'wav'
      ? t('settings.tts.transport.wav')
      : t('i18n.unknown')
  const locality = capabilities?.locality
    ? t(`settings.tts.locality.${capabilities.locality}`)
    : t('i18n.unknown')
  const providerId = snapshot?.provider || capabilities?.provider
  const provider = providerId === 'genie-tts'
    ? t('settings.tts.provider.genie')
    : providerId || t('i18n.unknown')
  const inputMode = capabilities
    ? capabilities.input_text_streaming
      ? t('settings.tts.input.incremental')
      : t('settings.tts.input.segment')
    : t('i18n.unknown')
  const alignment = capabilities?.alignment
    ? t(`settings.tts.alignment.${capabilities.alignment}`)
    : t('i18n.unknown')
  const cancellation = capabilities?.cancellation
    ? t(`settings.tts.cancellation.${capabilities.cancellation}`)
    : t('i18n.unknown')
  return [
    { label: t('settings.tts.metric.provider'), value: `${provider} · ${locality}` },
    { label: t('settings.tts.metric.input'), value: inputMode },
    { label: t('settings.tts.metric.transport'), value: transport },
    { label: t('settings.tts.metric.alignment'), value: alignment },
    { label: t('settings.tts.metric.cancellation'), value: cancellation },
    { label: t('settings.tts.metric.load'), value: formatTtsDuration(snapshot?.last_load_ms), detail: formatTtsLatencySummary(snapshot?.load_latency_summary?.total) },
    { label: t('settings.tts.metric.loadQueue'), value: formatTtsDuration(snapshot?.last_load_queue_ms), detail: formatTtsLatencySummary(snapshot?.load_latency_summary?.queue) },
    { label: t('settings.tts.metric.loadModel'), value: formatTtsDuration(snapshot?.last_load_model_ms), detail: formatTtsLatencySummary(snapshot?.load_latency_summary?.model) },
    { label: t('settings.tts.metric.warmup'), value: formatTtsDuration(snapshot?.last_warmup_ms), detail: formatTtsLatencySummary(snapshot?.warmup_latency_summary?.total) },
    { label: t('settings.tts.metric.warmupQueue'), value: formatTtsDuration(snapshot?.last_warmup_queue_ms), detail: formatTtsLatencySummary(snapshot?.warmup_latency_summary?.queue) },
    { label: t('settings.tts.metric.warmupInference'), value: formatTtsDuration(snapshot?.last_warmup_inference_ms), detail: formatTtsLatencySummary(snapshot?.warmup_latency_summary?.inference) },
    { label: t('settings.tts.metric.wait'), value: formatTtsDuration(snapshot?.last_ready_wait_ms), detail: formatTtsLatencySummary(snapshot?.ready_wait_latency_summary) },
    { label: t('settings.tts.metric.generation'), value: formatTtsDuration(snapshot?.last_generation_ms), detail: formatTtsLatencySummary(snapshot?.generation_latency_summary) },
    { label: t('settings.tts.metric.cancel'), value: formatTtsDuration(snapshot?.last_cancel_ms), detail: formatTtsLatencySummary(snapshot?.cancel_latency_summary) },
  ]
})

const themeOptions = computed(() => [
  { label: t('settings.theme.light'), value: 'light' },
  { label: t('settings.theme.dark'), value: 'dark' },
  { label: t('settings.theme.system'), value: 'system' },
])

const languageOptions = computed(() => supportedLocales.map((value) => ({ value, label: localeLabel(value) })))

const backendTokenConfigured = computed(() => Boolean(backendTokenStatus.value?.hasToken))
const backendTokenRequiresRestart = computed(() => Boolean(backendTokenStatus.value?.requiresRestart))
const backendTokenBusy = computed(() => backendTokenStatusRequest.loading || backendTokenMutationRequest.loading)
const backendTokenPreview = computed(() => {
  const status = backendTokenStatus.value
  if (!status) return ''
  return status.requiresRestart
    ? status.storedTokenPreview || status.tokenPreview
    : status.tokenPreview
})
const backendTokenSourceLabel = computed(() => {
  const source = backendTokenStatus.value?.source
  return source ? t(`settings.backendToken.source.${source}`) : t('i18n.unknown')
})

const isPlainRecord = (value: unknown): value is SettingsPatch => {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const resourceSummaryFallback = (message = '') => ({
  ready: false,
  state: 'missing' as const,
  message,
  details: [] as string[],
})

const normalizeResourceStatus = (value: unknown): ModelResourceStatusPayload | null => {
  if (!isPlainRecord(value)) return null
  const modelRoots = isPlainRecord(value.modelRoots) ? value.modelRoots : {}
  const localCounts = isPlainRecord(value.localCounts) ? value.localCounts : {}
  const soulx = isPlainRecord(value.soulx) ? value.soulx : {}
  const sherpa = isPlainRecord(value.sherpa) ? value.sherpa : {}
  const sherpaOnline = isPlainRecord(value.sherpaOnline) ? value.sherpaOnline : {}
  const embedding = isPlainRecord(value.embedding) ? value.embedding : {}
  const ttsStatus = isPlainRecord(value.tts) ? value.tts : {}
  const progressPhases = new Set<ResourceProgressPhase>(['preparing', 'downloading', 'verifying', 'extracting', 'installing', 'cancelling'])
  const activeDownloads = (Array.isArray(value.activeDownloads) ? value.activeDownloads : [])
    .filter(isPlainRecord)
    .flatMap((progress): ResourceDownloadProgress[] => {
      const resourceId = String(progress.resourceId || '') as ManagedModelResourceId
      const phase = progress.phase as ResourceProgressPhase
      if (!['soulx', 'sherpa', 'sherpa_online', 'embedding', 'tts'].includes(resourceId) || !progressPhases.has(phase)) return []
      const bytesDownloaded = progress.bytesDownloaded === null ? null : Math.max(0, Number(progress.bytesDownloaded || 0))
      const bytesTotal = progress.bytesTotal === null ? null : Math.max(0, Number(progress.bytesTotal || 0))
      const percent = progress.percent === null ? null : Math.min(100, Math.max(0, Number(progress.percent || 0)))
      return [{
        resourceId,
        phase,
        message: String(progress.message || ''),
        bytesDownloaded,
        bytesTotal,
        percent,
        startedAt: String(progress.startedAt || ''),
        updatedAt: String(progress.updatedAt || ''),
      }]
    })
  const resumableDownloads = (Array.isArray(value.resumableDownloads) ? value.resumableDownloads : [])
    .filter(isPlainRecord)
    .flatMap((download): ResumableResourceDownload[] => {
      const resourceId = String(download.resourceId || '') as ManagedModelResourceId
      if (!['soulx', 'sherpa', 'sherpa_online', 'embedding', 'tts'].includes(resourceId)) return []
      const bytesDownloaded = Math.max(0, Number(download.bytesDownloaded || 0))
      if (!Number.isFinite(bytesDownloaded) || bytesDownloaded <= 0) return []
      const rawBytesTotal = download.bytesTotal === null ? null : Number(download.bytesTotal || 0)
      const bytesTotal = rawBytesTotal !== null && Number.isFinite(rawBytesTotal)
        ? Math.max(bytesDownloaded, rawBytesTotal)
        : null
      const rawPercent = download.percent === null ? null : Number(download.percent || 0)
      const percent = rawPercent !== null && Number.isFinite(rawPercent)
        ? Math.min(100, Math.max(0, rawPercent))
        : null
      return [{
        resourceId,
        bytesDownloaded,
        bytesTotal,
        percent,
        updatedAt: String(download.updatedAt || ''),
      }]
    })
  const metadata = (source: SettingsPatch) => {
    const raw = isPlainRecord(source.metadata) ? source.metadata : {}
    const integrity = raw.integrity === 'sha256' || raw.integrity === 'revision' || raw.integrity === 'package' || raw.integrity === 'package+revision'
      ? raw.integrity
      : 'unverified'
    return {
      label: String(raw.label || ''),
      version: String(raw.version || ''),
      license: String(raw.license || ''),
      licenseUrl: String(raw.licenseUrl || ''),
      downloadBytes: Math.max(0, Number(raw.downloadBytes || 0)),
      source: String(raw.source || ''),
      integrity,
      inUseBy: Array.isArray(raw.inUseBy) ? raw.inUseBy.map(String) : [],
    }
  }
  const summary = (source: SettingsPatch, fallbackMessage: string) => ({
    ...resourceSummaryFallback(String(source.message || fallbackMessage)),
    ...source,
    ready: Boolean(source.ready),
    state: source.state === 'ready' || source.state === 'partial' ? source.state : 'missing',
    message: String(source.message || fallbackMessage),
    details: Array.isArray(source.details) ? source.details.map(String) : [],
    metadata: metadata(source),
  })
  return {
    modelRoots: {
      live2d: String(modelRoots.live2d || ''),
      vrm: String(modelRoots.vrm || ''),
    },
    localCounts: {
      live2d: Number(localCounts.live2d || 0),
      vrm: Number(localCounts.vrm || 0),
    },
    soulx: {
      ...summary(soulx, 'SoulX resources unavailable'),
      serviceDir: String(soulx.serviceDir || ''),
      launcherPath: String(soulx.launcherPath || ''),
      checkpointPath: typeof soulx.checkpointPath === 'string' ? soulx.checkpointPath : null,
      checkpointCandidates: Array.isArray(soulx.checkpointCandidates) ? soulx.checkpointCandidates.map(String) : [],
      preprocessDir: String(soulx.preprocessDir || ''),
      referenceDir: String(soulx.referenceDir || ''),
      hasReferenceAudio: Boolean(soulx.hasReferenceAudio),
    },
    sherpa: {
      ...summary(sherpa, 'Sherpa resources unavailable'),
      assetUrl: String(sherpa.assetUrl || ''),
      modelPath: String(sherpa.modelPath || ''),
      tokensPath: String(sherpa.tokensPath || ''),
      format: 'sensevoice-offline',
      validated: Boolean(sherpa.validated),
      validationPath: typeof sherpa.validationPath === 'string' ? sherpa.validationPath : null,
    },
    sherpaOnline: {
      ...summary(sherpaOnline, 'Sherpa streaming resources unavailable'),
      assetUrl: String(sherpaOnline.assetUrl || ''),
      modelPath: String(sherpaOnline.modelPath || ''),
      tokensPath: String(sherpaOnline.tokensPath || ''),
      format: 'zipformer2-ctc-online',
      validated: Boolean(sherpaOnline.validated),
      validationPath: typeof sherpaOnline.validationPath === 'string' ? sherpaOnline.validationPath : null,
    },
    embedding: {
      ...summary(embedding, 'Embedding resources unavailable'),
      modelName: String(embedding.modelName || ''),
      cachePath: typeof embedding.cachePath === 'string' ? embedding.cachePath : null,
      cacheRoot: String(embedding.cacheRoot || ''),
    },
    tts: {
      ...summary(ttsStatus, 'TTS resources unavailable'),
      character: String(ttsStatus.character || ''),
      cacheDir: String(ttsStatus.cacheDir || ''),
      modelDir: String(ttsStatus.modelDir || ''),
    },
    activeDownloads,
    resumableDownloads,
  }
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

const storageCategoryIds: StorageCategoryId[] = ['tts_audio', 'runtime_temp', 'memory', 'visual_frames']
const normalizeStorageStatus = (value: unknown): StorageStatusPayload | null => {
  if (!isPlainRecord(value) || !Array.isArray(value.categories)) return null
  const categories = value.categories.flatMap((rawCategory) => {
    if (!isPlainRecord(rawCategory)) return []
    const id = String(rawCategory.id || '') as StorageCategoryId
    if (!storageCategoryIds.includes(id)) return []
    const action = rawCategory.action === 'delete_files' || rawCategory.action === 'compact' ? rawCategory.action : 'none'
    return [{
      id,
      bytes: Math.max(0, Number(rawCategory.bytes || 0)),
      files: Math.max(0, Number(rawCategory.files || 0)),
      action,
      persistence: rawCategory.persistence === 'disk' ? 'disk' as const : 'memory_only' as const,
      failed_files: Math.max(0, Number(rawCategory.failed_files || 0)),
    }]
  })
  return {
    categories,
    total_bytes: Math.max(0, Number(value.total_bytes || 0)),
    reclaimable_bytes: Math.max(0, Number(value.reclaimable_bytes || 0)),
  }
}

const numberValue = (value: unknown, fallback: number): number => {
  const next = Number(value)
  return Number.isFinite(next) ? next : fallback
}

const stringValue = (value: unknown, fallback = ''): string => {
  return typeof value === 'string' ? value : fallback
}

const clearReactiveRecord = (record: Record<string, unknown>) => {
  Object.keys(record).forEach((key) => {
    delete record[key]
  })
}

const defaultLlmProfile = (provider: LlmProviderPreset): LlmProfile => ({
  provider,
  base_url: LLM_PROVIDER_BASE_URLS[provider] || '',
  api_key: '',
  model: '',
  temperature: 1.2,
  top_p: 0.9,
  top_k: 500,
  min_p: 0,
  frequency_penalty: 0.2,
  presence_penalty: 0,
  repetition_penalty: 1,
  timeout: 60,
  context_max_tokens: DEFAULT_LLM_CONTEXT_MAX_TOKENS,
  default_max_output_tokens: DEFAULT_LLM_MAX_OUTPUT_TOKENS,
})

const sanitizeLlmProfile = (provider: LlmProviderPreset, value?: Partial<LlmProfile> | null): LlmProfile => {
  const defaults = defaultLlmProfile(provider)
  const nextProvider = normalizeLlmProviderValue(stringValue(value?.provider, provider), stringValue(value?.base_url, defaults.base_url))
  const baseUrl = normalizeOpenAiBaseUrl(stringValue(value?.base_url, defaults.base_url || LLM_PROVIDER_BASE_URLS[nextProvider] || ''))
  return {
    provider: nextProvider,
    base_url: baseUrl,
    api_key: KEYLESS_LLM_PROVIDERS.has(nextProvider) ? '' : stringValue(value?.api_key, ''),
    model: stringValue(value?.model, defaults.model),
    temperature: numberValue(value?.temperature, defaults.temperature),
    top_p: numberValue(value?.top_p, defaults.top_p),
    top_k: numberValue(value?.top_k, defaults.top_k),
    min_p: numberValue(value?.min_p, defaults.min_p),
    frequency_penalty: numberValue(value?.frequency_penalty, defaults.frequency_penalty),
    presence_penalty: numberValue(value?.presence_penalty, defaults.presence_penalty),
    repetition_penalty: numberValue(value?.repetition_penalty, defaults.repetition_penalty),
    timeout: numberValue(value?.timeout, defaults.timeout),
    context_max_tokens: numberValue(value?.context_max_tokens, defaults.context_max_tokens),
    default_max_output_tokens: numberValue(value?.default_max_output_tokens, defaults.default_max_output_tokens),
  }
}

const snapshotLlmProfile = (provider = llmProviderPreset.value): LlmProfile => sanitizeLlmProfile(provider, form.llm)

const applyLlmProfileToForm = (profile: LlmProfile) => {
  form.llm.provider = profile.provider
  form.llm.base_url = profile.base_url
  form.llm.api_key = KEYLESS_LLM_PROVIDERS.has(profile.provider) ? '' : profile.api_key
  form.llm.model = profile.model
  form.llm.temperature = profile.temperature
  form.llm.top_p = profile.top_p
  form.llm.top_k = profile.top_k
  form.llm.min_p = profile.min_p
  form.llm.frequency_penalty = profile.frequency_penalty
  form.llm.presence_penalty = profile.presence_penalty
  form.llm.repetition_penalty = profile.repetition_penalty
  form.llm.timeout = profile.timeout
  form.llm.context_max_tokens = profile.context_max_tokens
  form.llm.default_max_output_tokens = profile.default_max_output_tokens
}

const llmRuntimePatchFromProfile = (profile: LlmProfile): SettingsPatch => ({
  provider: profile.provider,
  base_url: profile.base_url,
  api_key: profile.api_key,
  model: profile.model,
  temperature: profile.temperature,
  top_p: profile.top_p,
  top_k: profile.top_k,
  min_p: profile.min_p,
  frequency_penalty: profile.frequency_penalty,
  presence_penalty: profile.presence_penalty,
  repetition_penalty: profile.repetition_penalty,
  timeout: profile.timeout,
  context_max_tokens: profile.context_max_tokens,
  default_max_output_tokens: profile.default_max_output_tokens,
})

const cloneLlmProfilesPayload = (activeProfile?: LlmProfile): Record<string, LlmProfile> => {
  const payload: Record<string, LlmProfile> = {}
  if (activeProfile) {
    llmProfiles[activeProfile.provider] = activeProfile
  }
  for (const [key, profile] of Object.entries(llmProfiles)) {
    const provider = normalizeLlmProviderValue(key, profile?.base_url || '')
    payload[provider] = sanitizeLlmProfile(provider, profile)
  }
  return payload
}

const saveActiveLlmPatch = (patch: SettingsPatch) => {
  const activeProfile = snapshotLlmProfile()
  llmProfiles[activeProfile.provider] = activeProfile
  debouncedSave({ llm: { ...patch, profiles: cloneLlmProfilesPayload(activeProfile) } })
}

const saveLlmField = (field: LlmProfileField, value: unknown) => {
  if (field === 'api_key' && !llmProviderNeedsApiKey.value) {
    form.llm.api_key = ''
    saveActiveLlmPatch({ api_key: '' })
    return
  }
  saveActiveLlmPatch({ [field]: value })
}

const defaultTtsProfile = (): TtsProfile => {
  return {
    genie_character: '',
    genie_model_dir: '',
    ref_audio: '',
    ref_text: '',
    lang: 'ja',
    device: 'cpu',
    quality: '质量优先',
    split: '智能切分',
    mode: '串行推理',
    save_mode: '禁用自动保存',
    provider: TTS_PROVIDER,
  }
}

const sanitizeTtsProfile = (value?: Partial<TtsProfile> | null): TtsProfile => {
  const defaults = defaultTtsProfile()
  const device = stringValue(value?.device, defaults.device)
  return {
    genie_character: stringValue(value?.genie_character, defaults.genie_character),
    genie_model_dir: stringValue(value?.genie_model_dir, defaults.genie_model_dir),
    ref_audio: stringValue(value?.ref_audio, defaults.ref_audio),
    ref_text: stringValue(value?.ref_text, defaults.ref_text),
    lang: stringValue(value?.lang, defaults.lang),
    device: device === 'cuda' ? 'cuda' : 'cpu',
    quality: stringValue(value?.quality, defaults.quality),
    split: stringValue(value?.split, defaults.split),
    mode: stringValue(value?.mode, defaults.mode),
    save_mode: '禁用自动保存',
    provider: TTS_PROVIDER,
  }
}

const snapshotTtsProfile = (): TtsProfile => sanitizeTtsProfile({
  ...form.tts,
})

const applyTtsProfileToForm = (profile: TtsProfile) => {
  form.tts.genie_character = profile.genie_character
  form.tts.genie_model_dir = profile.genie_model_dir
  form.tts.ref_audio = profile.ref_audio
  form.tts.ref_text = profile.ref_text
  form.tts.lang = profile.lang
  form.tts.device = profile.device
  form.tts.quality = profile.quality
  form.tts.split = profile.split
  form.tts.mode = profile.mode
  form.tts.save_mode = profile.save_mode
  form.tts.provider = profile.provider
}

const ttsRuntimePatchFromProfile = (profile: TtsProfile): SettingsPatch => ({
  genie_character: profile.genie_character,
  genie_model_dir: profile.genie_model_dir,
  ref_audio: profile.ref_audio,
  ref_text: profile.ref_text,
  lang: profile.lang,
  device: profile.device,
  quality: profile.quality,
  split: profile.split,
  mode: profile.mode,
  save_mode: profile.save_mode,
  provider: profile.provider,
})

const saveActiveTtsPatch = (patch: SettingsPatch) => {
  const activeProfile = snapshotTtsProfile()
  debouncedSave({ tts: { ...ttsRuntimePatchFromProfile(activeProfile), ...patch, provider: TTS_PROVIDER, save_mode: '禁用自动保存' } })
}

const setTtsFormField = (field: TtsProfileField, value: unknown) => {
  if (field === 'provider') {
    form.tts.provider = TTS_PROVIDER
    return
  }
  if (field === 'device') {
    form.tts.device = value === 'cuda' ? 'cuda' : 'cpu'
    return
  }
  if (field === 'save_mode') {
    form.tts.save_mode = '禁用自动保存'
    return
  }
  form.tts[field] = String(value ?? '')
}

const flushTtsSave = () => {
  void flushPendingSave()
}

const saveTtsField = (field: TtsProfileField, value: unknown, options?: SaveFieldOptions) => {
  setTtsFormField(field, value)
  saveActiveTtsPatch({ [field]: value })
  if (options?.flush) flushTtsSave()
}

const readLlmProfileForStatus = (provider: LlmProviderPreset): LlmProfile => {
  if (provider === llmProviderPreset.value) {
    return sanitizeLlmProfile(provider, { ...form.llm, provider })
  }
  return sanitizeLlmProfile(provider, llmProfiles[provider] || defaultLlmProfile(provider))
}

const getLlmProviderStatus = (provider: LlmProviderPreset): { status: string; statusClass: ProviderStatusClass } => {
  const profile = readLlmProfileForStatus(provider)
  if (!profile.base_url.trim()) {
    return { status: t('settings.providerStatus.missing'), statusClass: 'muted' }
  }
  if (llmProfileNeedsApiKey(profile) && !profile.api_key.trim()) {
    return { status: t('settings.providerStatus.missingKey'), statusClass: 'warning' }
  }
  if (!profile.model.trim()) {
    return { status: t('settings.providerStatus.modelMissing'), statusClass: 'warning' }
  }
  return { status: t('settings.providerStatus.ready'), statusClass: 'ready' }
}

const ttsProfileHasRunnableConfig = (profile: TtsProfile): boolean => {
  return Boolean(profile.genie_character.trim() || (profile.ref_audio.trim() && profile.ref_text.trim()))
}

const llmProviderOptionRows = computed(() => llmProviderOptions.value.map((option) => ({
  ...option,
  ...getLlmProviderStatus(option.value),
})))

const hasLlmEndpoint = computed(() => Boolean(form.llm.base_url.trim() && form.llm.model.trim()))
const hasLlmApiKey = computed(() => !llmProviderNeedsApiKey.value || Boolean(form.llm.api_key.trim()))
const canRequestLlmModels = computed(() => Boolean(normalizeOpenAiBaseUrl(form.llm.base_url) && hasLlmApiKey.value))
const hasTtsVoice = computed(() => {
  return ttsProfileHasRunnableConfig(sanitizeTtsProfile(form.tts))
})
const hasSvcEndpoint = computed(() => Boolean(form.svc.provider !== 'disabled' && form.svc.base_url.trim()))
const llmEndpointSummary = computed(() => {
  const value = normalizeOpenAiBaseUrl(form.llm.base_url)
  if (!value) return t('settings.llm.summaryMissing')
  try {
    const url = new URL(value)
    return `${url.hostname}${url.pathname === '/' ? '' : url.pathname}`.replace(/\/$/, '')
  } catch {
    return value
  }
})
const llmEndpointAppendLabel = computed(() => {
  const endpoints = LLM_PROVIDER_ENDPOINTS[llmProviderPreset.value] || LLM_PROVIDER_ENDPOINTS.custom
  return `${endpoints.modelsPath} + ${endpoints.chatPath}`
})
const llmModelSummary = computed(() => form.llm.model.trim() || t('settings.llm.summaryMissing'))
const llmAuthSummary = computed(() => {
  if (!llmProviderNeedsApiKey.value) return t('settings.llm.apiKeyNotRequired')
  return form.llm.api_key.trim() ? t('settings.llm.apiKeySaved') : t('settings.llm.apiKeyMissing')
})
const llmModelSelectOptions = computed(() => {
  const current = form.llm.model.trim()
  const options = [...llmModels.value]
  if (current && !options.includes(current)) {
    options.unshift(current)
  }
  return options
})

const llmDetectionStatus = computed(() => {
  if (llmModelsRequest.loading) return t('settings.llm.detection.detecting')
  if (llmModelsRequest.error) return t('settings.llm.detection.failed')
  if (llmModels.value.length) return llmModelAutoSelected.value ? t('settings.llm.detection.autoSelected') : t('settings.llm.detection.detected')
  return t('settings.llm.detection.none')
})

const llmDetectionTagType = computed(() => {
  if (llmModelsRequest.error) return 'danger'
  if (llmModelsRequest.loading) return 'warning'
  if (llmModels.value.length) return 'success'
  return 'info'
})

const llmModelStatusLabel = computed(() => {
  if (llmModelsRequest.loading) return t('settings.llm.modelsReading')
  if (llmModelsRequest.error) return llmModelsRequest.error
  return llmModelStatus.value
})

const canAutoDiscoverLlmModels = computed(() => {
  return shouldAutoDiscoverLlmModels(form.llm.base_url, llmProviderNeedsApiKey.value ? form.llm.api_key : '')
})

const currentModelCapabilities = computed(() => inferModelCapabilities(llmProviderPreset.value, form.llm.model))
const formatTokenLimit = (value: number | null) => value === null ? '未知' : value.toLocaleString('en-US')
const modelLifecycleLabel = computed(() => ({
  stable: '稳定',
  preview: '预览',
  deprecated: '即将停用',
  legacy: '旧版',
  unknown: '未知',
}[currentModelCapabilities.value.metadata?.lifecycle || 'unknown']))
const modelCapabilitySourceLabel = computed(() => {
  const metadata = currentModelCapabilities.value.metadata
  if (currentModelCapabilities.value.source === 'registry' && metadata) {
    return `官方资料登记 · 核验 ${metadata.verifiedAt}`
  }
  if (currentModelCapabilities.value.source === 'model-pattern') return '根据模型名推断，请以提供商文档为准'
  return '未识别，请以服务端文档为准'
})
const modelMetadataRows = computed(() => {
  const metadata = currentModelCapabilities.value.metadata
  if (!metadata) return []
  return [
    { label: '上下文窗口', value: `${formatTokenLimit(metadata.contextWindowTokens)} tokens` },
    { label: '最大输出', value: `${formatTokenLimit(metadata.maxOutputTokens)} tokens` },
    { label: '生命周期', value: modelLifecycleLabel.value },
    { label: '规范模型', value: metadata.canonicalModel },
  ]
})
const modelPricingLabel = computed(() => {
  const pricing = currentModelCapabilities.value.metadata?.pricing
  if (!pricing) return ''
  const cached = pricing.cachedInputPerMillionUsd === undefined
    ? ''
    : `，缓存命中输入 $${pricing.cachedInputPerMillionUsd}`
  const note = pricing.note ? `；${pricing.note}` : ''
  return `参考价（每 100 万 tokens）：输入 $${pricing.inputPerMillionUsd}，输出 $${pricing.outputPerMillionUsd}${cached}${note}`
})
const modelConfigurationWarnings = computed(() => {
  const metadata = currentModelCapabilities.value.metadata
  if (!metadata) return []
  const warnings: string[] = []
  if (metadata.lifecycle === 'deprecated') {
    const date = metadata.deprecationAt ? new Date(metadata.deprecationAt).toLocaleString() : '提供商公布的停用时间'
    warnings.push(`当前模型别名将于 ${date} 停用，建议切换到 ${metadata.canonicalModel}。`)
  }
  if (metadata.contextWindowTokens !== null && Number(form.llm.context_max_tokens) > metadata.contextWindowTokens) {
    warnings.push(`当前上下文配置 ${formatTokenLimit(Number(form.llm.context_max_tokens))} 超过登记上限 ${formatTokenLimit(metadata.contextWindowTokens)}。`)
  }
  if (metadata.maxOutputTokens !== null && Number(form.llm.default_max_output_tokens) > metadata.maxOutputTokens) {
    warnings.push(`当前最大输出 ${formatTokenLimit(Number(form.llm.default_max_output_tokens))} 超过登记上限 ${formatTokenLimit(metadata.maxOutputTokens)}。`)
  }
  if (currentModelCapabilities.value.vision === false && !form.llm.vision_enabled) {
    warnings.push('当前文本模型不支持视觉；启用实时屏幕观察前，请配置独立视觉模型。')
  }
  return warnings
})
const modelCapabilityRows = computed(() => [
  { key: 'vision', label: '视觉', support: currentModelCapabilities.value.vision },
  { key: 'tools', label: '工具', support: currentModelCapabilities.value.tools },
  { key: 'structuredOutput', label: '结构化输出', support: currentModelCapabilities.value.structuredOutput },
  { key: 'realtimeAudio', label: '实时音频', support: currentModelCapabilities.value.realtimeAudio },
  { key: 'computerUse', label: '电脑操作', support: currentModelCapabilities.value.computerUse },
])
const capabilitySupportLabel = (support: ModelCapabilitySupport) => support === true ? '支持' : support === false ? '不支持' : '未知'
const capabilityTagType = (support: ModelCapabilitySupport): TagType => support === true ? 'success' : support === false ? 'info' : 'warning'
const modelLatencyLabel = computed(() => ({
  realtime: '延迟 · 实时',
  fast: '延迟 · 快',
  balanced: '延迟 · 均衡',
  deliberate: '延迟 · 深度',
  unknown: '延迟 · 未知',
}[currentModelCapabilities.value.latency]))
const modelLatencyTagType = computed<TagType>(() => currentModelCapabilities.value.latency === 'realtime'
  ? 'success'
  : currentModelCapabilities.value.latency === 'fast'
    ? 'success'
    : currentModelCapabilities.value.latency === 'unknown'
      ? 'warning'
      : 'info')

const saveBusy = computed(() => updateRequest.loading || saveInFlight.value || Boolean(pendingSavePatch.value))

const saveStatusType = computed<AlertType>(() => {
  if (saveBusy.value) return 'warning'
  if (updateRequest.error) return 'error'
  if (lastSavedAt.value) return 'success'
  return 'info'
})

const saveStatusLabel = computed(() => {
  if (saveBusy.value) return t('settings.status.saving')
  if (updateRequest.error) return t('settings.status.saveFailed')
  if (lastSavedAt.value) return t('settings.status.saved')
  return ''
})

const saveStatusDetail = computed(() => {
  if (saveBusy.value) return t('settings.status.savingShort')
  if (updateRequest.error) return updateRequest.error
  if (lastApplied.value.length) return t('settings.status.applied', { items: lastApplied.value.join(' / ') })
  if (lastSavedAt.value) return t('settings.status.recent', { time: lastSavedAt.value })
  return ''
})

const resourceActionLoading = (key: string) => resourceActionKey.value === key

const resourceTagType = (state: 'missing' | 'partial' | 'ready') => {
  if (state === 'ready') return 'success'
  if (state === 'partial') return 'warning'
  return 'danger'
}

const resourceView = computed(() => normalizeResourceStatus(resourceStatus.value))
const activeDownloadProgress = computed(() => resourceView.value?.activeDownloads ?? [])
const cancellableResourceIds = computed<ManagedModelResourceId[]>(() => [...new Set([
  ...activeResourceIds.value,
  ...activeDownloadProgress.value.map((progress) => progress.resourceId),
])])
type ResourceDownloadOption = {
  id: ManagedModelResourceId
  label: string
  ready: boolean
  version: string
  license: string
  downloadBytes: number
  resumable: ResumableResourceDownload | null
}
const resourceDownloadOptions = computed<ResourceDownloadOption[]>(() => {
  const status = resourceView.value
  if (!status) return []
  const options: Array<Omit<ResourceDownloadOption, 'resumable'>> = [
    { ...status.sherpaOnline.metadata, id: 'sherpa_online', label: '流式语音识别', ready: status.sherpaOnline.ready },
    { ...status.sherpa.metadata, id: 'sherpa', label: '离线语音识别', ready: status.sherpa.ready },
    { ...status.tts.metadata, id: 'tts', label: 'Genie TTS', ready: status.tts.ready },
    { ...status.embedding.metadata, id: 'embedding', label: '长期记忆嵌入', ready: status.embedding.ready },
    { ...status.soulx.metadata, id: 'soulx', label: 'SoulX 变声', ready: status.soulx.ready },
  ]
  return options.map((item) => ({
    ...item,
    resumable: status.resumableDownloads.find((download) => download.resourceId === item.id) ?? null,
  }))
})

const formatStorageBytes = (value: number): string => {
  const bytes = Math.max(0, Number(value) || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GiB`
}

const formatResourceDownloadBytes = (value: number): string => value > 0 ? formatStorageBytes(value) : '按模型'

const resourceProgressLabels: Record<ManagedModelResourceId, string> = {
  soulx: 'SoulX 变声',
  sherpa: '离线语音识别',
  sherpa_online: '流式语音识别',
  embedding: '长期记忆嵌入',
  tts: 'Genie TTS',
}
const resourceProgressPhaseLabels: Record<ResourceProgressPhase, string> = {
  preparing: '准备',
  downloading: '下载',
  verifying: '校验',
  extracting: '解压',
  installing: '安装',
  cancelling: '取消中',
}
const resourceProgressLabel = (resourceId: ManagedModelResourceId): string => resourceProgressLabels[resourceId]
const resourceProgressPhaseLabel = (phase: ResourceProgressPhase): string => resourceProgressPhaseLabels[phase]

const storageCategoryLabel = (id: StorageCategoryId): string => t(`settings.storage.category.${id}`)

const notifySaveIdle = () => {
  if (saveInFlight.value || pendingSavePatch.value) return
  const resolvers = saveIdleResolvers
  saveIdleResolvers = []
  resolvers.forEach((resolve) => resolve(true))
}

const waitForSaveIdle = async () => {
  if (!saveInFlight.value && !pendingSavePatch.value) return
  await new Promise<boolean>((resolve) => saveIdleResolvers.push(resolve))
}

const promoteFailedSavePatch = () => {
  if (!failedSavePatch.value) return
  pendingSavePatch.value = pendingSavePatch.value
    ? mergePatch(failedSavePatch.value, pendingSavePatch.value)
    : failedSavePatch.value
  failedSavePatch.value = null
}

const queueSavePatch = (patch: SettingsPatch) => {
  promoteFailedSavePatch()
  pendingSavePatch.value = pendingSavePatch.value
    ? mergePatch(pendingSavePatch.value, patch)
    : patch
}

const savePatch = async (patch: SettingsPatch) => {
  const result = await patchSettings(patch)
  if (unmounted) return result
  if (result) {
    const appliedSections = result.runtime_applied || result.runtime_changed || []
    lastSavedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    lastApplied.value = appliedSections
    if (appliedSections.includes('tts')) {
      window.setTimeout(() => {
        void loadTtsStatus()
      }, 500)
    }
    void prepareResourcesForSettingsPatch(patch)
  } else {
    ElMessage.error(t('settings.messages.saveFailed'))
  }
  return result
}

const parkFailedSavePatch = (patch: SettingsPatch | null) => {
  if (!patch) return
  const queuedAfterFailure = pendingSavePatch.value
  pendingSavePatch.value = null
  failedSavePatch.value = queuedAfterFailure
    ? mergePatch(patch, queuedAfterFailure)
    : patch
}

let flushSaveAfterUnmount = false

const drainSaveQueue = async (options: { allowAfterUnmount?: boolean } = {}) => {
  if (options.allowAfterUnmount) flushSaveAfterUnmount = true
  if (saveInFlight.value) return
  saveInFlight.value = true
  let activePatch: SettingsPatch | null = null
  try {
    while (pendingSavePatch.value && (!unmounted || flushSaveAfterUnmount)) {
      activePatch = pendingSavePatch.value
      pendingSavePatch.value = null
      const result = await savePatch(activePatch)
      if (!result) {
        saveFailureCount += 1
        parkFailedSavePatch(activePatch)
        break
      }
      activePatch = null
    }
  } catch (error) {
    console.error('[Settings Save Queue]:', error)
    saveFailureCount += 1
    parkFailedSavePatch(activePatch)
    if (!unmounted) ElMessage.error(t('settings.messages.saveFailed'))
  } finally {
    saveInFlight.value = false
    if (!pendingSavePatch.value) flushSaveAfterUnmount = false
    notifySaveIdle()
  }
}

const debouncedSave = (patch: SettingsPatch) => {
  if (unmounted) return
  if (saveTimeout) clearTimeout(saveTimeout)
  queueSavePatch(patch)

  saveTimeout = setTimeout(() => {
    saveTimeout = null
    void drainSaveQueue()
  }, 1000)
}

const flushPendingSave = async () => {
  const failureCountBeforeFlush = saveFailureCount
  if (saveTimeout) {
    clearTimeout(saveTimeout)
    saveTimeout = null
  }
  promoteFailedSavePatch()
  void drainSaveQueue()
  await waitForSaveIdle()
  return saveFailureCount === failureCountBeforeFlush && !failedSavePatch.value
}

const setMemoryBackend = (backend: string) => {
  if (form.memory.backend === backend) return
  form.memory.backend = backend
  debouncedSave({ memory: { backend } })
}

const handleMemoryBackendChange = (value: string | number | boolean) => {
  setMemoryBackend(String(value))
}

const waitForMemoryBackend = async (expectedBackend: string) => {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const status = await memoryClient.getIndexStatus()
    if (status.backend === expectedBackend) return true
    await new Promise<void>((resolve) => window.setTimeout(resolve, 100))
  }
  return false
}

const handleRebuildMemoryIndex = async () => {
  if (form.memory.backend === 'inmemory') {
    ElMessage.warning('In-memory 后端没有持久化索引可重建')
    return
  }
  if (!(await flushPendingSave())) return
  if (!(await waitForMemoryBackend(form.memory.backend))) {
    ElMessage.error('记忆后端仍在切换，请稍后重试')
    return
  }
  const result = await memoryRebuildRequest.execute(() => memoryClient.rebuildIndex())
  if (!result) {
    ElMessage.error(memoryRebuildRequest.error || t('settings.messages.memoryRebuildFailed'))
    return
  }
  const indexed = Number(result.indexed_count ?? 0)
  const skipped = Number(result.skipped_count ?? 0)
  ElMessage.success(t('settings.messages.memoryRebuildOk', { count: indexed, skipped }))
}

const handleSystemThemeChange = (value: string | number | boolean) => {
  const rawTheme = String(value || 'light')
  const nextTheme = ['light', 'dark', 'system'].includes(rawTheme) ? rawTheme : 'light'
  form.system.theme = nextTheme
  settingsStore.state.system.theme = nextTheme
  debouncedSave({ system: { theme: nextTheme } })
}

const handleSystemLanguageChange = async (value: string | number | boolean) => {
  const nextLocale = normalizeLocale(String(value ?? ''))
  form.system.language = nextLocale
  try {
    await setLocale(nextLocale)
    ElMessage.success(t('language.changed'))
  } catch {
    ElMessage.warning(t('common.localOnly'))
  }
}

const updateDesktopInputBindings = async (patch: InputBindingSettingsPatch) => {
  try {
    await inputBindingsStore.update(patch)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '桌面快捷键保存失败')
  }
}

const setPushToTalkEnabled = (value: string | number | boolean) => {
  void updateDesktopInputBindings({ pushToTalk: { enabled: Boolean(value) } })
}

const setPushToTalkMouseButton = (value: unknown) => {
  const mouseButton: MouseSideButton = Number(value) === 4 ? 4 : 5
  void updateDesktopInputBindings({ pushToTalk: { mouseButton } })
}

const keyboardEventKey = (event: KeyboardEvent): string | null => {
  const aliases: Record<string, string> = {
    ' ': 'Space',
    ArrowUp: 'Up',
    ArrowDown: 'Down',
    ArrowLeft: 'Left',
    ArrowRight: 'Right',
    Esc: 'Escape',
  }
  const key = aliases[event.key] ?? event.key
  if (['Control', 'Shift', 'Alt', 'Meta'].includes(key)) return null
  if (/^[a-z0-9]$/i.test(key)) return key.toUpperCase()
  if (/^F(?:[1-9]|1\d|2[0-4])$/.test(key)) return key
  if (['Space', 'Tab', 'Enter', 'Escape', 'Up', 'Down', 'Left', 'Right', 'Home', 'End', 'PageUp', 'PageDown', 'Insert', 'Delete'].includes(key)) {
    return key
  }
  return null
}

const captureKeyboardBinding = (action: KeyboardShortcutAction, event: KeyboardEvent) => {
  const key = keyboardEventKey(event)
  if (!key) return
  const modifiers: string[] = []
  if (event.ctrlKey) modifiers.push('Control')
  if (event.metaKey) modifiers.push('Command')
  if (event.altKey) modifiers.push('Alt')
  if (event.shiftKey) modifiers.push('Shift')
  if (!modifiers.length && !key.startsWith('F')) {
    ElMessage.warning('字母、数字和导航键至少需要一个修饰键')
    return
  }
  void updateDesktopInputBindings({ keyboard: { [action]: [...modifiers, key].join('+') } })
  ;(event.currentTarget as HTMLInputElement | null)?.blur()
}

const clearKeyboardBinding = (action: KeyboardShortcutAction) => {
  void updateDesktopInputBindings({ keyboard: { [action]: '' } })
}

const resetDesktopInputBindings = async () => {
  try {
    await inputBindingsStore.reset()
    ElMessage.success('桌面输入已恢复默认')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '恢复默认失败')
  }
}

const discoverLocalRuntime = async (): Promise<LocalRuntimeDiscoveryResponse | null> => {
  const result = await localDiscoveryRequest.execute(() => settingsClient.discoverLocal())
  if (!result) {
    ElMessage.error(localDiscoveryRequest.error || t('settings.messages.localDetectFailed'))
    return null
  }
  return result
}

const firstReadyCandidate = (items: LocalRuntimeCandidate[] | undefined): LocalRuntimeCandidate | null => {
  return items?.find((item) => item.ok) ?? null
}

const warnNoLocalCandidate = (service: string) => {
  ElMessage.warning(t('settings.messages.localDetectNone', { service }))
}

const notifyLocalCandidateApplied = (candidate: LocalRuntimeCandidate, fallback: string) => {
  ElMessage.success(t('settings.messages.localDetectApplied', { service: candidate.label || candidate.provider || candidate.backend || fallback }))
}

const applyLocalLlmDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  if (!discovery) return
  const currentProvider = llmProviderPreset.value
  const candidate = discovery.llm.find((item) => item.ok && item.provider === currentProvider)
    ?? firstReadyCandidate(discovery.llm)
  if (!candidate?.base_url) {
    warnNoLocalCandidate('LLM')
    return
  }

  const provider = normalizeLlmProviderValue(String(candidate.provider || ''), candidate.base_url)
  const models = (candidate.models || []).map(String).filter(Boolean)
  const nextModel = models.length
    ? choosePreferredLlmModel(models, provider)
    : form.llm.model
  const nextProfile = sanitizeLlmProfile(provider, {
    ...form.llm,
    provider,
    base_url: candidate.base_url,
    api_key: '',
    model: nextModel,
  })
  llmProviderPreset.value = provider
  llmModels.value = models
  llmModelAutoSelected.value = Boolean(models.length && nextModel)
  llmModelStatus.value = candidate.message || ''
  applyLlmProfileToForm(nextProfile)
  llmProfiles[provider] = nextProfile
  saveActiveLlmPatch(llmRuntimePatchFromProfile(nextProfile))
  notifyLocalCandidateApplied(candidate, 'LLM')
}

const applyLocalAsrDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  const candidate = firstReadyCandidate(discovery?.asr)
  if (!candidate?.base_url) {
    warnNoLocalCandidate('ASR')
    return
  }
  const provider = String(candidate.provider || 'sherpa-onnx-online')
  form.asr.provider = provider
  form.asr.base_url = candidate.base_url
  debouncedSave({ asr: { provider, base_url: candidate.base_url } })
  notifyLocalCandidateApplied(candidate, 'ASR')
}

const applyLocalTtsDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  const candidate = firstReadyCandidate(discovery?.tts)
  if (!candidate) {
    warnNoLocalCandidate('Genie TTS')
    return
  }
  const patch: SettingsPatch = { provider: TTS_PROVIDER }
  const modelDir = typeof candidate.model_dir === 'string' ? candidate.model_dir : ''
  if (modelDir && candidate.model_dir_exists) {
    form.tts.genie_model_dir = modelDir
    patch.genie_model_dir = modelDir
  }
  saveActiveTtsPatch(patch)
  if (!candidate.model_dir_exists && candidate.installed) {
    ElMessage.success(t('settings.messages.localTtsLibraryDetected'))
    return
  }
  notifyLocalCandidateApplied(candidate, 'Genie TTS')
}

const applyLocalSvcDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  const candidate = firstReadyCandidate(discovery?.svc)
  if (!candidate?.base_url) {
    warnNoLocalCandidate('SoulX SVC')
    return
  }
  form.svc.provider = 'soulx-service'
  form.svc.base_url = candidate.base_url
  debouncedSave({ svc: { provider: 'soulx-service', base_url: candidate.base_url } })
  notifyLocalCandidateApplied(candidate, 'SoulX SVC')
}

const applyLocalMemoryDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  const candidate = firstReadyCandidate(discovery?.memory)
  if (!candidate?.qdrant_url) {
    warnNoLocalCandidate('Qdrant')
    return
  }
  form.memory.backend = 'qdrant'
  form.memory.qdrant_url = candidate.qdrant_url
  debouncedSave({ memory: { backend: 'qdrant', qdrant_url: candidate.qdrant_url } })
  notifyLocalCandidateApplied(candidate, 'Qdrant')
}

const applyLlmProviderPreset = (value: string | number | boolean) => {
  const preset = String(value) as LlmProviderPreset
  if (!(preset in LLM_PROVIDER_BASE_URLS)) {
    llmProviderPreset.value = 'custom'
    return
  }

  const previousProvider = normalizeLlmProviderValue(form.llm.provider, form.llm.base_url)
  const previousProfile = snapshotLlmProfile(previousProvider)
  llmProfiles[previousProfile.provider] = previousProfile
  llmProviderPreset.value = preset
  const nextProfile = sanitizeLlmProfile(preset, llmProfiles[preset] || defaultLlmProfile(preset))
  applyLlmProfileToForm(nextProfile)
  llmProfiles[preset] = snapshotLlmProfile(preset)
  llmModelAutoSelected.value = false
  llmModels.value = []
  llmModelStatus.value = ''
  saveActiveLlmPatch(llmRuntimePatchFromProfile(nextProfile))
  scheduleLlmModelDiscovery({ manual: false })
}

const resetCurrentLlmProfile = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.resetProviderProfileMessage', { provider: activeLlmProfileLabel.value }),
      t('settings.confirm.resetProviderProfileTitle'),
      {
        confirmButtonText: t('common.reset'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const provider = llmProviderPreset.value
  const nextProfile = defaultLlmProfile(provider)
  llmProfiles[provider] = nextProfile
  applyLlmProfileToForm(nextProfile)
  llmModels.value = []
  llmModelStatus.value = ''
  llmModelAutoSelected.value = false
  saveActiveLlmPatch(llmRuntimePatchFromProfile(nextProfile))
  scheduleLlmModelDiscovery({ manual: false })
  ElMessage.success(t('settings.messages.providerProfileReset'))
}

const resetCurrentTtsProfile = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.resetProviderProfileMessage', { provider: activeTtsProviderLabel.value }),
      t('settings.confirm.resetProviderProfileTitle'),
      {
        confirmButtonText: t('common.reset'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const nextProfile = defaultTtsProfile()
  applyTtsProfileToForm(nextProfile)
  saveActiveTtsPatch(ttsRuntimePatchFromProfile(nextProfile))
  ElMessage.success(t('settings.messages.providerProfileReset'))
}

const shouldAutoSelectLlmModel = (models: string[], options?: LlmModelDiscoveryOptions): boolean => {
  const current = form.llm.model.trim()
  if (options?.forceAutoSelect) return true
  if (!current) return true
  return !models.includes(current)
}

const applyDetectedLlmModel = (models: string[], options?: LlmModelDiscoveryOptions) => {
  if (!shouldAutoSelectLlmModel(models, options)) {
    llmModelAutoSelected.value = false
    return
  }

  const nextModel = choosePreferredLlmModel(models, llmProviderPreset.value)
  if (!nextModel || form.llm.model.trim() === nextModel) return

  form.llm.model = nextModel
  llmModelAutoSelected.value = true
  saveLlmField('model', nextModel)
}

const firstString = (source: SettingsPatch, keys: string[]): string | undefined => {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'string') return value
  }
  return undefined
}

const firstNumber = (source: SettingsPatch, keys: string[]): number | undefined => {
  for (const key of keys) {
    const value = source[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value)
  }
  return undefined
}

const normalizeLlmProviderValue = (value: string | undefined, baseUrl = ''): LlmProviderPreset => {
  const normalized = value?.trim().toLowerCase()
  if (normalized && normalized in LLM_PROVIDER_BASE_URLS) return normalized as LlmProviderPreset
  if (normalized === 'openai') return 'chatgpt'
  if (normalized === 'anthropic') return 'claude'
  if (normalized === 'xai' || normalized === 'x-ai') return 'grok'
  if (normalized === 'dashscope') return 'qwen'
  if (normalized === 'ollama') return 'ollama'
  if (normalized === 'lm-studio' || normalized === 'lm_studio') return 'lmstudio'
  if (normalized === 'azure' || normalized === 'azure-compatible' || normalized === 'openai-compatible') return 'custom'
  return inferLlmProviderPreset(baseUrl)
}

const normalizeLlmProfilePayload = (payload: unknown): SettingsPatch | null => {
  if (!isPlainRecord(payload)) return null
  const knownSections = ['llm', 'tts', 'asr', 'svc', 'summary', 'memory', 'system']
  if (knownSections.some((key) => isPlainRecord(payload[key]))) {
    return payload
  }

  const nestedProfile = ['connectionProfile', 'profile', 'preset', 'api', 'connection']
    .map((key) => payload[key])
    .find(isPlainRecord)
  const source = nestedProfile || payload
  const llm: SettingsPatch = {}
  const stringFields: Array<[keyof typeof form.llm, string[]]> = [
    ['provider', ['provider', 'llmProvider', 'providerPreset']],
    ['base_url', ['base_url', 'baseUrl', 'api_url', 'apiUrl', 'server_url', 'serverUrl', 'endpoint']],
    ['api_key', ['api_key', 'apiKey', 'key', 'token', 'secret']],
    ['model', ['model', 'model_name', 'modelName', 'chat_model', 'chatModel']],
  ]
  for (const [target, keys] of stringFields) {
    const value = firstString(source, keys)
        if (typeof value === 'string') {
          llm[target] = target === 'base_url'
            ? normalizeOpenAiBaseUrl(value)
            : target === 'provider'
              ? normalizeLlmProviderValue(value, firstString(source, ['base_url', 'baseUrl', 'endpoint']) || '')
              : value
        }
  }

  const numberFields: Array<[keyof typeof form.llm, string[]]> = [
    ['timeout', ['timeout', 'request_timeout', 'requestTimeout']],
    ['context_max_tokens', ['context_max_tokens', 'contextMaxTokens', 'context_size', 'contextSize', 'max_context', 'maxContext', 'openai_max_context', 'openaiMaxContext']],
    ['default_max_output_tokens', ['default_max_output_tokens', 'max_output_tokens', 'maxOutputTokens', 'max_tokens', 'maxTokens', 'openai_max_tokens', 'openaiMaxTokens']],
    ['temperature', ['temperature', 'temp']],
    ['top_p', ['top_p', 'topP']],
    ['top_k', ['top_k', 'topK']],
    ['min_p', ['min_p', 'minP']],
    ['frequency_penalty', ['frequency_penalty', 'frequencyPenalty']],
    ['presence_penalty', ['presence_penalty', 'presencePenalty']],
    ['repetition_penalty', ['repetition_penalty', 'repetitionPenalty', 'repeat_penalty', 'repeatPenalty', 'rep_penalty', 'repPenalty']],
  ]
  for (const [target, keys] of numberFields) {
    const value = firstNumber(source, keys)
    if (typeof value === 'number') llm[target] = value
  }

  return Object.keys(llm).length ? { llm } : null
}

const triggerLlmImport = () => {
  llmImportInput.value?.click()
}

const saveJsonDownload = (payload: unknown, filename: string) => {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

const buildLlmProfilePayload = (useCurrentValues: boolean) => {
  const profile = useCurrentValues ? snapshotLlmProfile() : defaultLlmProfile('custom')
  return {
    kind: 'yuizaki-llm-profile',
    version: 1,
    credentialMode: 'provider-profile',
    provider: profile.provider,
    connectionProfile: {
      name: useCurrentValues ? activeLlmProfileLabel.value : t('common.custom'),
      credentialMode: 'provider-profile',
      provider: profile.provider,
      baseUrl: normalizeOpenAiBaseUrl(profile.base_url),
      apiKey: profile.api_key,
      modelName: profile.model,
      timeout: profile.timeout,
      contextMaxTokens: profile.context_max_tokens,
      maxTokens: profile.default_max_output_tokens,
      temperature: profile.temperature,
      topP: profile.top_p,
      topK: profile.top_k,
      minP: profile.min_p,
      frequencyPenalty: profile.frequency_penalty,
      presencePenalty: profile.presence_penalty,
      repetitionPenalty: profile.repetition_penalty,
    },
  }
}

const downloadLlmProfileTemplate = () => {
  saveJsonDownload(buildLlmProfilePayload(false), 'yuizaki-llm-profile-template.json')
  ElMessage.success(t('settings.messages.templateOk'))
}

const applyImportedSettings = async (payload: unknown) => {
  const normalized = normalizeLlmProfilePayload(payload)
  if (!normalized) {
    ElMessage.error(t('settings.messages.importInvalid'))
    return
  }
  llmImporting.value = true
  try {
    if (!(await flushPendingSave())) return
    const result = await settingsClient.importPayload(normalized)
    lastSavedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    lastApplied.value = result.runtime_applied || result.runtime_changed || []
    await loadSettings()
    hydrateForm()
    scheduleLlmModelDiscovery({ manual: false })
    ElMessage.success(t('settings.messages.importOk'))
  } catch (error) {
    ElMessage.error(t('settings.messages.importFailed', { message: error instanceof Error ? error.message : t('common.error.unknown') }))
  } finally {
    llmImporting.value = false
  }
}

const handleLlmImportFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const payload = JSON.parse(await file.text()) as unknown
    await applyImportedSettings(payload)
  } catch (error) {
    ElMessage.error(t('settings.messages.importFailed', { message: error instanceof Error ? error.message : t('settings.messages.importInvalid') }))
  }
}

const exportLlmProfile = async () => {
  llmExporting.value = true
  try {
    const stamp = new Date().toISOString().slice(0, 10)
    saveJsonDownload(buildLlmProfilePayload(true), `yuizaki-llm-profile-${stamp}.json`)
    ElMessage.success(t('settings.messages.exportOk'))
  } catch (error) {
    ElMessage.error(t('settings.messages.exportFailed', { message: error instanceof Error ? error.message : t('common.error.unknown') }))
  } finally {
    llmExporting.value = false
  }
}

const refreshAdminTokenStatus = async () => {
  const result = await adminTokenRequest.execute(() => settingsClient.adminTokenStatus())
  if (result) {
    adminTokenConfigured.value = result.hasToken
  }
  return result
}

const refreshBackendTokenStatus = async () => {
  const result = await backendTokenStatusRequest.execute(() => settingsClient.backendTokenStatus())
  if (result) {
    backendTokenStatus.value = result
  }
  return result
}

const saveAdminToken = async () => {
  const token = adminTokenInput.value.trim()
  if (!token) {
    ElMessage.warning(t('settings.messages.adminRequired'))
    return
  }

  const result = await adminTokenRequest.execute(async () => {
    const response = await settingsClient.setAdminToken(token)
    return { ok: response.ok, hasToken: Boolean(response.hasToken) }
  })
  if (!result?.ok) return

  adminTokenConfigured.value = result.hasToken
  adminTokenInput.value = ''
  ElMessage.success(t('settings.messages.adminUnlocked'))
  if (!(await flushPendingSave())) return
  await loadSettings()
  hydrateForm()
  if (!settingsRequest.error) {
    await loadSettingsAdmin()
    scheduleLlmModelDiscovery()
  }
}

const clearAdminToken = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.clearAdminTokenMessage'),
      t('settings.confirm.clearAdminTokenTitle'),
      {
        confirmButtonText: t('common.clear'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const result = await adminTokenRequest.execute(async () => {
    const response = await settingsClient.clearAdminToken()
    return { ok: response.ok, hasToken: false }
  })
  if (!result?.ok) return

  adminTokenConfigured.value = false
  adminTokenInput.value = ''
  ElMessage.success(t('settings.messages.adminCleared'))
}

const saveBackendToken = async () => {
  const token = backendTokenInput.value.trim()
  if (!token) {
    ElMessage.warning(t('settings.messages.backendTokenRequired'))
    return
  }

  const result = await backendTokenMutationRequest.execute(() => settingsClient.setBackendToken(token))
  if (!result?.ok) return

  backendTokenInput.value = ''
  await refreshBackendTokenStatus()
  ElMessage.success(result.requiresRestart ? t('settings.messages.backendTokenSavedRestart') : t('settings.messages.backendTokenSaved'))
}

const resetBackendToken = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.resetBackendTokenMessage'),
      t('settings.confirm.resetBackendTokenTitle'),
      {
        confirmButtonText: t('settings.backendToken.reset'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  const result = await backendTokenMutationRequest.execute(() => settingsClient.resetBackendToken())
  if (!result?.ok) return

  backendTokenInput.value = ''
  await refreshBackendTokenStatus()
  ElMessage.success(result.requiresRestart ? t('settings.messages.backendTokenResetRestart') : t('settings.messages.backendTokenReset'))
}

const handleTestLlm = async () => {
  if (!(await flushPendingSave())) return
  const res = await testLlm()
  if (res?.status === 'ok' || res?.ok) {
    ElMessage.success(t('settings.messages.llmOk'))
  } else if (res) {
    ElMessage.error(t('settings.messages.llmFailed', { message: res.message || t('common.error.unknown') }))
  }
}

const refreshTtsStatus = async (): Promise<TtsRuntimeStatusResponse | null> => {
  return loadTtsStatus()
}

const queueTtsWarmup = async () => {
  const snapshot = ttsStatus.value
  if (warmupTtsRequest.loading || snapshot?.warmup_done || snapshot?.warmup_running || snapshot?.warming_up) return
  const result = await warmupTts()
  if (result?.ok) {
    void loadTtsStatus()
  }
}

const handleTestTts = async () => {
  if (!(await flushPendingSave())) return
  const res = await testTts()
  await refreshTtsStatus()
  if (res?.status === 'ok' || res?.ok) {
    ElMessage.success(t('settings.messages.ttsOk'))
  } else if (res) {
    ElMessage.error(t('settings.messages.ttsFailed', { message: res.message || t('settings.messages.ttsHint') }))
  }
}

const loadSettingsAdmin = async () => {
  try {
    settingsMetadata.value = await settingsClient.metadata()
    const history = await settingsClient.history()
    settingsHistory.value = history.history
  } catch (error) {
    settingsMetadata.value = null
    settingsHistory.value = []
    console.info('[Settings] Admin metadata unavailable:', error)
  }
}

const rollbackSettings = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.rollbackMessage', { steps: rollbackSteps.value }),
      t('settings.confirm.rollbackTitle'),
      {
        confirmButtonText: t('common.rollback'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    if (!(await flushPendingSave())) return
    await settingsClient.rollback(rollbackSteps.value)
    ElMessage.success(t('settings.messages.rollbackOk'))
    await loadSettings()
    hydrateForm()
    await loadSettingsAdmin()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('common.error.unknown'))
  }
}

const clearSettingsHistory = async () => {
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.clearHistoryMessage'),
      t('settings.confirm.clearHistoryTitle'),
      {
        confirmButtonText: t('settings.admin.clearHistory'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    await settingsClient.clearHistory()
    settingsHistory.value = []
    ElMessage.success(t('settings.messages.historyCleared'))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('common.error.unknown'))
  }
}

const stopResourceProgressPolling = () => {
  if (resourceProgressPollTimer === null) return
  window.clearInterval(resourceProgressPollTimer)
  resourceProgressPollTimer = null
}

const pollResourceStatus = async () => {
  if (resourceProgressPollBusy) return
  resourceProgressPollBusy = true
  try {
    resourceStatus.value = normalizeResourceStatus(await resourceClient.status())
  } catch {
    // The foreground command reports actionable failures; polling stays silent.
  } finally {
    resourceProgressPollBusy = false
    if (!resourceActionKey.value && activeDownloadProgress.value.length === 0) stopResourceProgressPolling()
  }
}

const syncResourceProgressPolling = () => {
  const shouldPoll = Boolean(resourceActionKey.value) || activeDownloadProgress.value.length > 0
  if (!shouldPoll) {
    stopResourceProgressPolling()
    return
  }
  if (resourceProgressPollTimer !== null) return
  resourceProgressPollTimer = window.setInterval(() => void pollResourceStatus(), 500)
}

const loadResourceStatus = async () => {
  resourceLoading.value = true
  try {
    resourceStatus.value = normalizeResourceStatus(await resourceClient.status())
    syncResourceProgressPolling()
  } catch (error) {
    const message = error instanceof Error ? error.message : t('settings.resource.statusFailed')
    resourceMessage.value = message
    resourceMessageType.value = 'error'
    ElMessage.error(message)
  } finally {
    resourceLoading.value = false
  }
}

const runResourceCommand = async (
  key: string,
  task: () => Promise<ResourceCommandResult>,
  resources: ManagedModelResourceId[] = [],
) => {
  if (resourceActionKey.value || activeDownloadProgress.value.length > 0) {
    ElMessage.warning('已有资源任务正在执行')
    return
  }
  resourceActionKey.value = key
  activeResourceIds.value = [...resources]
  resourceMessage.value = ''
  syncResourceProgressPolling()
  try {
    const result = await task()
    resourceStatus.value = normalizeResourceStatus(result.status)
    resourceMessage.value = result.message
    resourceMessageType.value = result.success ? 'success' : 'warning'
    if (result.success) {
      ElMessage.success(result.message)
    } else {
      ElMessage.warning(result.message)
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : t('settings.resource.taskFailed')
    resourceMessage.value = message
    resourceMessageType.value = 'error'
    ElMessage.error(message)
  } finally {
    resourceActionKey.value = ''
    activeResourceIds.value = []
    syncResourceProgressPolling()
  }
}

const cancelActiveResourceDownloads = async () => {
  const resources = [...cancellableResourceIds.value]
  if (resources.length === 0 || resourceCancelLoading.value) return
  resourceCancelLoading.value = true
  try {
    const result = await resourceClient.cancel(resources)
    resourceStatus.value = normalizeResourceStatus(result.status)
    const message = result.cancelled.length > 0 ? `已取消 ${result.cancelled.length} 个下载任务` : '没有可取消的下载任务'
    resourceMessage.value = message
    resourceMessageType.value = result.cancelled.length > 0 ? 'success' : 'info'
    if (result.cancelled.length > 0) {
      ElMessage.success(message)
    } else {
      ElMessage.info(message)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('settings.resource.taskFailed'))
  } finally {
    resourceCancelLoading.value = false
  }
}

const removeModelResource = async (
  resourceId: ManagedModelResourceId,
  label: string,
  metadata: ManagedResourceMetadata,
) => {
  if (resourceActionKey.value) {
    ElMessage.warning('请先完成或取消当前资源任务')
    return
  }
  const usage = metadata.inUseBy.length > 0 ? ` · 使用中：${metadata.inUseBy.join(' / ')}` : ''
  try {
    await ElMessageBox.confirm(
      `${label} · ${formatResourceDownloadBytes(metadata.downloadBytes)}${usage}`,
      '永久卸载模型',
      {
        confirmButtonText: '永久卸载',
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  resourceActionKey.value = `remove-${resourceId}`
  try {
    const result = await resourceClient.remove([resourceId])
    resourceStatus.value = normalizeResourceStatus(result.status)
    resourceMessage.value = result.message
    resourceMessageType.value = result.success ? 'success' : 'warning'
    if (result.success) {
      ElMessage.success(`已永久卸载 ${label}，释放 ${formatStorageBytes(result.reclaimedBytes)}`)
    } else {
      ElMessage.warning(result.failed.map((item) => item.reason).join('; ') || result.message)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('settings.resource.taskFailed'))
  } finally {
    resourceActionKey.value = ''
  }
}

const handleLlmModelChange = (value: string | number | boolean) => {
  llmModelAutoSelected.value = false
  saveLlmField('model', String(value ?? ''))
}

const loadStorageStatus = async () => {
  storageLoading.value = true
  try {
    storageStatus.value = normalizeStorageStatus(await resourceClient.storageStatus())
  } catch (error) {
    storageStatus.value = null
    ElMessage.error(error instanceof Error ? error.message : t('settings.storage.loadFailed'))
  } finally {
    storageLoading.value = false
  }
}

const resourceIdsForSettingsPatch = (patch: SettingsPatch): ManagedModelResourceId[] => {
  const ids: ManagedModelResourceId[] = []
  const asr = patch.asr as { provider?: unknown } | undefined
  const tts = patch.tts as Record<string, unknown> | undefined
  const svc = patch.svc as { provider?: unknown } | undefined
  const memory = patch.memory as { embedding_model?: unknown } | undefined
  if (asr?.provider === 'sherpa-onnx-online') ids.push('sherpa_online')
  if (asr?.provider === 'sherpa-onnx') ids.push('sherpa')
  if (tts) ids.push('tts')
  if (svc?.provider === 'soulx-service') ids.push('soulx')
  if (typeof memory?.embedding_model === 'string') ids.push('embedding')
  return [...new Set(ids)]
}

const prepareResourcesForSettingsPatch = async (patch: SettingsPatch) => {
  const ids = resourceIdsForSettingsPatch(patch)
  if (ids.length === 0) return
  await runResourceCommand('first-use-download', () => resourceClient.prepare(ids), ids)
}

const downloadSelectedResources = async () => {
  const ids = [...selectedResourceIds.value]
  if (ids.length === 0) return
  await runResourceCommand('selected-download', () => resourceClient.prepare(ids), ids)
  selectedResourceIds.value = selectedResourceIds.value.filter((id) => {
    const item = resourceDownloadOptions.value.find((option) => option.id === id)
    return item ? !item.ready : false
  })
}

const refreshResourcePanel = async () => {
  await Promise.all([loadResourceStatus(), loadStorageStatus()])
}

const cleanupStorage = async (targets: StorageCleanupTarget[]) => {
  if (!storageStatus.value || !targets.length) return
  const selected = storageStatus.value.categories.filter((item) => targets.includes(item.id as StorageCleanupTarget))
  const selectedFiles = selected.reduce((sum, item) => sum + item.files, 0)
  const selectedBytes = selected.reduce((sum, item) => sum + item.bytes, 0)
  const selectedLabels = selected.map((item) => storageCategoryLabel(item.id)).join(' / ')
  try {
    await ElMessageBox.confirm(
      `${selectedLabels} · ${selectedFiles} ${t('settings.storage.files')} · ${formatStorageBytes(selectedBytes)}`,
      t('settings.storage.confirmTitle'),
      {
        confirmButtonText: t('settings.storage.confirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  storageActionKey.value = targets.length > 1 ? 'all' : targets[0]
  try {
    const result = await resourceClient.cleanupStorage(targets)
    storageStatus.value = normalizeStorageStatus(result.status)
    if (result.failed_files > 0) {
      ElMessage.warning(t('settings.storage.partial', { count: result.failed_files }))
    } else {
      ElMessage.success(t('settings.storage.cleaned', {
        files: result.deleted_files,
        size: formatStorageBytes(result.reclaimed_bytes),
      }))
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('settings.storage.cleanFailed'))
  } finally {
    storageActionKey.value = ''
  }
}

const cleanupAllStorage = async () => {
  const targets = (storageStatus.value?.categories || [])
    .filter((item) => item.action === 'delete_files' && item.files > 0)
    .map((item) => item.id as StorageCleanupTarget)
  await cleanupStorage(targets)
}

const discoverLlmModels = async (options?: LlmModelDiscoveryOptions) => {
  const baseUrl = normalizeOpenAiBaseUrl(form.llm.base_url)
  if (!baseUrl) {
    llmModels.value = []
    llmModelStatus.value = ''
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }
  if (!options?.manual && !canAutoDiscoverLlmModels.value) {
    llmModels.value = []
    llmModelStatus.value = t('settings.llm.modelsSkippedNoKey')
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }

  const runId = ++modelDiscoveryRun
  const result = await loadLlmModels({
    provider: llmProviderPreset.value,
    base_url: baseUrl,
    api_key: llmProviderNeedsApiKey.value ? form.llm.api_key.trim() : '',
    timeout: form.llm.timeout,
  })
  if (runId !== modelDiscoveryRun) return

  if (result?.ok) {
    applyDetectedLlmModel(result.models, options)
    llmModelStatus.value = result.models.length
      ? t('settings.llm.modelsDetected', {
        count: result.models.length,
        selected: llmModelAutoSelected.value ? t('settings.llm.modelsSelected', { model: form.llm.model }) : '',
      })
      : (result.message || t('settings.llm.modelsEmpty'))
  } else if (result) {
    llmModelStatus.value = result.message || t('settings.llm.modelsFailed')
    llmModelAutoSelected.value = false
  }
}

const scheduleLlmModelDiscovery = (options?: LlmModelDiscoveryOptions) => {
  if (suppressModelDiscovery) return
  if (modelDiscoveryTimeout) clearTimeout(modelDiscoveryTimeout)
  if (!normalizeOpenAiBaseUrl(form.llm.base_url)) {
    llmModels.value = []
    llmModelStatus.value = ''
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }
  if (!options?.manual && !canAutoDiscoverLlmModels.value) {
    llmModels.value = []
    llmModelStatus.value = t('settings.llm.modelsSkippedNoKey')
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }
  modelDiscoveryTimeout = setTimeout(() => {
    void discoverLlmModels(options)
  }, 650)
}

const handleLlmEndpointChange = (field: 'base_url' | 'api_key', value: string | number | boolean) => {
  if (field === 'base_url') {
    const normalizedBaseUrl = normalizeOpenAiBaseUrl(String(value ?? ''))
    const previousProvider = normalizeLlmProviderValue(form.llm.provider, form.llm.base_url)
    const inferredProvider = inferLlmProviderPreset(normalizedBaseUrl)
    if (inferredProvider !== previousProvider) {
      if (!llmProfiles[previousProvider]) {
        llmProfiles[previousProvider] = snapshotLlmProfile(previousProvider)
      }
      llmProviderPreset.value = inferredProvider
      const nextProfile = sanitizeLlmProfile(inferredProvider, {
        ...(llmProfiles[inferredProvider] || defaultLlmProfile(inferredProvider)),
        base_url: normalizedBaseUrl,
      })
      applyLlmProfileToForm(nextProfile)
    } else {
      form.llm.base_url = normalizedBaseUrl
      form.llm.provider = llmProviderPreset.value
    }
    if (!llmProviderNeedsApiKey.value) {
      form.llm.api_key = ''
    }
    llmModelAutoSelected.value = false
    saveActiveLlmPatch({
      provider: llmProviderPreset.value,
      base_url: normalizedBaseUrl,
      api_key: form.llm.api_key,
    })
    scheduleLlmModelDiscovery({ manual: false })
    return
  }
  llmModelAutoSelected.value = false
  form.llm.api_key = llmProviderNeedsApiKey.value ? String(value ?? '') : ''
  saveLlmField(field, form.llm.api_key)
  if (field === 'api_key') {
    if (modelDiscoveryTimeout) clearTimeout(modelDiscoveryTimeout)
    modelDiscoveryTimeout = setTimeout(async () => {
      await flushPendingSave()
      await discoverLlmModels({ manual: false })
    }, 700)
    return
  }
  scheduleLlmModelDiscovery({ manual: false })
}

const readSettingKey = async () => {
  if (!lookupKey.value.trim()) return
  const result = await settingsClient.getSetting(lookupKey.value.trim())
  lookupResult.value = JSON.stringify(result, null, 2)
}

const parseSettingValue = (): unknown => {
  const raw = setValueJson.value.trim()
  try {
    return JSON.parse(raw)
  } catch {
    return raw
  }
}

const writeSettingKey = async () => {
  if (!setKey.value.trim() || !setValueJson.value.trim()) return
  if (!(await flushPendingSave())) return
  await settingsClient.setSetting(setKey.value.trim(), parseSettingValue())
  ElMessage.success(t('settings.messages.settingWritten'))
  await loadSettings()
  hydrateForm()
  await loadSettingsAdmin()
}

const resetSettingKey = async () => {
  const key = deleteKey.value.trim()
  if (!key) return
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.deleteKeyMessage', { key }),
      t('settings.confirm.deleteKeyTitle'),
      {
        confirmButtonText: t('common.delete'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  try {
    if (!(await flushPendingSave())) return
    await settingsClient.deleteSetting(key)
    ElMessage.success(t('settings.messages.settingReset'))
    deleteKey.value = ''
    await loadSettings()
    hydrateForm()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('common.error.unknown'))
  }
}

const hydrateForm = () => {
  if (!settings.value) return
  const s = settings.value
  suppressModelDiscovery = true

  if (s.llm) {
    clearReactiveRecord(llmProfiles as Record<string, unknown>)
    for (const [key, profile] of Object.entries(s.llm.profiles || {})) {
      const provider = normalizeLlmProviderValue(key, profile?.base_url || '')
      llmProfiles[provider] = sanitizeLlmProfile(provider, profile as Partial<LlmProfile>)
    }
    const activeProvider = normalizeLlmProviderValue(s.llm.provider, s.llm.base_url)
    const activeProfile = sanitizeLlmProfile(activeProvider, {
      ...(llmProfiles[activeProvider] || {}),
      provider: activeProvider,
      base_url: s.llm.base_url ?? '',
      api_key: s.llm.api_key ?? '',
      model: s.llm.model ?? '',
      temperature: s.llm.temperature ?? 1.2,
      top_p: s.llm.top_p ?? 0.9,
      top_k: s.llm.top_k ?? 500,
      min_p: s.llm.min_p ?? 0,
      frequency_penalty: s.llm.frequency_penalty ?? 0.2,
      presence_penalty: s.llm.presence_penalty ?? 0,
      repetition_penalty: s.llm.repetition_penalty ?? 1,
      timeout: s.llm.timeout ?? 60,
      context_max_tokens: s.llm.context_max_tokens ?? DEFAULT_LLM_CONTEXT_MAX_TOKENS,
      default_max_output_tokens: s.llm.default_max_output_tokens ?? DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    })
    llmProfiles[activeProvider] = activeProfile
    llmProviderPreset.value = activeProvider
    applyLlmProfileToForm(activeProfile)
    form.llm.vision_enabled = s.llm.vision_enabled ?? false
    form.llm.vision_provider = normalizeLlmProviderValue(s.llm.vision_provider, s.llm.vision_base_url)
    form.llm.vision_base_url = s.llm.vision_base_url ?? ''
    form.llm.vision_api_key = s.llm.vision_api_key ?? ''
    form.llm.vision_model = s.llm.vision_model ?? ''
    form.llm.vision_timeout = s.llm.vision_timeout ?? 30
    form.llm.vision_detail = s.llm.vision_detail ?? 'low'
    llmModelAutoSelected.value = false
  }

  if (s.tts) {
    const activeProfile = sanitizeTtsProfile({
      genie_character: s.tts.genie_character ?? '',
      genie_model_dir: s.tts.genie_model_dir || '',
      ref_audio: s.tts.ref_audio ?? '',
      ref_text: s.tts.ref_text ?? '',
      lang: s.tts.lang || 'ja',
      device: s.tts.device || 'cpu',
      quality: s.tts.quality || '质量优先',
      split: s.tts.split || '智能切分',
      mode: s.tts.mode || '串行推理',
      save_mode: s.tts.save_mode || '禁用自动保存',
      provider: TTS_PROVIDER,
    })
    applyTtsProfileToForm(activeProfile)
  }

  if (s.asr) {
    form.asr.provider = s.asr.provider || 'sherpa-onnx-online'
    form.asr.base_url = s.asr.base_url ?? ''
    form.asr.api_key = s.asr.api_key || ''
    form.asr.timeout = s.asr.timeout ?? 60
    form.asr.sensevoice_model = s.asr.sensevoice_model || 'iic/SenseVoiceSmall'
    form.asr.sensevoice_device = s.asr.sensevoice_device || 'cpu'
    form.asr.sherpa_model_path = s.asr.sherpa_model_path || ''
    form.asr.sherpa_tokens_path = s.asr.sherpa_tokens_path || ''
    form.asr.sherpa_num_threads = s.asr.sherpa_num_threads ?? 2
    form.asr.sherpa_provider = s.asr.sherpa_provider || 'cpu'
  form.asr.language = s.asr.language || 'zh'
    form.asr.vad_threshold = s.asr.vad_threshold ?? 0.5
    form.asr.vad_min_silence_ms = s.asr.vad_min_silence_ms ?? DEFAULT_VAD_MIN_SILENCE_MS
    form.asr.asr_partial_every = s.asr.asr_partial_every ?? 15
  }

  if (s.svc) {
    form.svc.provider = s.svc.provider || 'soulx-service'
    form.svc.base_url = s.svc.base_url ?? ''
    form.svc.speaker_id = s.svc.speaker_id ?? 0
    form.svc.pitch = s.svc.pitch ?? 0
    form.svc.timeout = s.svc.timeout ?? 120
  }

  if (s.summary) {
    form.summary.trigger_messages = s.summary.trigger_messages ?? 24
    form.summary.keep_recent_messages = s.summary.keep_recent_messages ?? 8
    form.summary.item_max_chars = s.summary.item_max_chars ?? 140
    form.summary.rewrite_interval_messages = s.summary.rewrite_interval_messages ?? 6
    form.summary.quality_scorer_mode = s.summary.quality_scorer_mode ?? 'rule'
    form.summary.quality_score_cooldown_seconds = s.summary.quality_score_cooldown_seconds ?? 300
    form.summary.quality_score_budget_per_hour = s.summary.quality_score_budget_per_hour ?? 20
  }

  if (s.memory) {
    form.memory.backend = s.memory.backend ?? 'sqlite'
    form.memory.sqlite_path = s.memory.sqlite_path ?? ''
    form.memory.qdrant_url = s.memory.qdrant_url ?? ''
    form.memory.qdrant_api_key = s.memory.qdrant_api_key ?? ''
    form.memory.qdrant_collection = s.memory.qdrant_collection ?? 'memories'
    form.memory.qdrant_timeout = s.memory.qdrant_timeout ?? 10
    form.memory.qdrant_auto_start = s.memory.qdrant_auto_start ?? true
    form.memory.qdrant_docker_image = s.memory.qdrant_docker_image ?? DEFAULT_QDRANT_DOCKER_IMAGE
    form.memory.qdrant_docker_container = s.memory.qdrant_docker_container ?? 'yuizaki-qdrant'
    form.memory.qdrant_docker_volume = s.memory.qdrant_docker_volume ?? 'yuizaki-qdrant-storage'
    form.memory.embedding_model = s.memory.embedding_model ?? DEFAULT_EMBEDDING_MODEL
    form.memory.reranker_enabled = s.memory.reranker_enabled ?? false
    form.memory.reranker_model = s.memory.reranker_model ?? 'BAAI/bge-reranker-v2-m3'
    form.memory.reranker_candidate_count = s.memory.reranker_candidate_count ?? 32
  }

  if (s.system) {
    form.system.language = normalizeLocale(s.system.language || currentLocale.value)
    form.system.theme = s.system.theme || 'light'
  }

  suppressModelDiscovery = false
}

onMounted(async () => {
  await Promise.all([refreshAdminTokenStatus(), refreshBackendTokenStatus(), inputBindingsStore.load()])
  await loadSettings()
  hydrateForm()
  if (!settingsRequest.error) {
    await loadSettingsAdmin()
  }
  await Promise.all([loadResourceStatus(), loadStorageStatus(), loadTtsStatus()])
  void queueTtsWarmup()
  scheduleLlmModelDiscovery({ manual: false })
})

onBeforeUnmount(() => {
  if (saveTimeout) {
    clearTimeout(saveTimeout)
    saveTimeout = null
  }
  promoteFailedSavePatch()
  if (pendingSavePatch.value) {
    void drainSaveQueue({ allowAfterUnmount: true })
  }
})

onUnmounted(() => {
  unmounted = true
  if (modelDiscoveryTimeout) clearTimeout(modelDiscoveryTimeout)
  saveTimeout = null
  modelDiscoveryTimeout = null
  stopResourceProgressPolling()
  notifySaveIdle()
})

watch(currentLocale, (value) => {
  form.system.language = value
})

watch(activeSection, (value) => {
  if (value === 'voice') {
    void queueTtsWarmup()
  }
})
</script>

<style scoped>
.settings-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.card-header,
.button-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.button-row {
  justify-content: flex-start;
  flex-wrap: wrap;
}

.llm-toolbar {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-end;
  gap: 9px;
}

.tts-toolbar {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.llm-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px 12px;
  min-width: 0;
}

.llm-action-group {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  min-width: 0;
  padding: 3px;
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-muted);
}

.llm-action-group + .llm-action-group {
  margin-left: 2px;
}

.llm-status-strip {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  max-width: 560px;
}

.tts-status-strip {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  max-width: 560px;
}

.header-title,
.profile-rail-head,
.profile-card,
.credential-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.header-title span,
.profile-rail-head strong,
.profile-card strong,
.credential-card strong {
  color: var(--yui-text);
  font-weight: 750;
}

.profile-card span,
.credential-card span {
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
}

.sr-only-input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.llm-workspace,
.voice-workspace {
  display: grid;
  grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.llm-profile-rail,
.voice-provider-rail {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-muted);
}

.provider-stack {
  display: grid;
  gap: 6px;
}

.provider-stack :deep(.el-radio-button__inner) {
  display: flex;
  align-items: center;
  width: 100%;
  justify-content: flex-start;
  border-radius: 8px;
  text-align: left;
  font-weight: 650;
}

.provider-stack :deep(.el-radio-button:first-child .el-radio-button__inner),
.provider-stack :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 8px;
}

.provider-option-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  min-width: 0;
}

.provider-option-label strong {
  overflow: hidden;
  color: inherit;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-option-label small {
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 700;
}

.provider-option-label .status-ready {
  color: #047857;
}

.provider-option-label .status-warning {
  color: #b45309;
}

.provider-option-label .status-muted {
  color: var(--yui-muted);
}

.profile-reset-button {
  width: 100%;
  justify-content: center;
}

.profile-card,
.credential-card {
  padding: 10px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-raised);
}

.credential-card {
  border-color: color-mix(in srgb, var(--yui-accent) 34%, var(--yui-border));
  background: color-mix(in srgb, var(--yui-accent) 8%, var(--yui-surface-raised));
}

.credential-card.empty {
  border-color: var(--yui-border);
  background: var(--yui-surface);
}

.llm-connection-summary {
  display: grid;
  gap: 8px;
}

.summary-row {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface);
}

.summary-row span {
  color: var(--yui-muted);
  font-size: 11px;
}

.summary-row strong {
  overflow-wrap: anywhere;
  color: var(--yui-text);
  font-size: 12px;
  font-weight: 700;
  line-height: 1.35;
}

.llm-main-form,
.voice-main-form {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-raised);
}

.tts-runtime-panel {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(156px, 1fr));
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
}

.tts-runtime-item {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.tts-runtime-item span {
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.3;
}

.tts-runtime-item small {
  color: var(--yui-muted);
  font-size: 10px;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

.tts-runtime-item strong {
  overflow: hidden;
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 760;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tts-runtime-alert {
  margin-bottom: 12px;
}

.subsection-title {
  margin: 2px 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--yui-border);
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 760;
}

.parameter-strip {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
  padding: 13px 14px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
}

.settings-access-card {
  border-color: var(--yui-border);
  background: var(--yui-surface);
}

.settings-access-card :deep(.el-card__body) {
  padding: 12px 14px;
}

.access-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.access-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.access-row strong {
  color: var(--yui-text);
  font-size: 14px;
}

.access-divider {
  height: 1px;
  background: var(--yui-border);
}

.access-token-details {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.access-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 7px;
  min-width: min(560px, 100%);
  flex-wrap: wrap;
}

.admin-token-input {
  max-width: 250px;
}

.backend-token-input {
  max-width: 300px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
  min-width: 0;
}

.form-grid.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.full-width {
  width: 100%;
}

.field-hint {
  margin: 6px 0 0;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.4;
}

.field-hint.error {
  color: #dc2626;
}

.model-capability-panel {
  width: 100%;
  margin-top: 8px;
  padding: 10px;
  border: 1px solid var(--yui-border);
  border-radius: 8px;
  background: var(--yui-surface-muted);
}

.model-capability-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.model-capability-head strong {
  color: var(--yui-text);
  font-size: 12px;
}

.model-capability-head span {
  color: var(--yui-muted);
  font-size: 11px;
  text-align: right;
}

.model-capability-head a {
  margin-left: 5px;
  color: var(--el-color-primary);
}

.model-capability-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.model-metadata-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 12px;
  margin-top: 9px;
}

.model-metadata-grid > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
  color: var(--yui-muted);
  font-size: 11px;
}

.model-metadata-grid strong {
  overflow-wrap: anywhere;
  color: var(--yui-text);
  font-size: 11px;
  text-align: right;
}

.model-pricing-note {
  margin: 8px 0 0;
  color: var(--yui-muted);
  font-size: 11px;
  line-height: 1.45;
}

.model-capability-warning {
  margin-top: 8px;
}

@media (max-width: 720px) {
  .model-metadata-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.desktop-input-card,
.settings-admin-card {
  margin-top: 16px;
}

.desktop-input-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 14px;
}

.desktop-input-row,
.keyboard-binding-row {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto minmax(220px, 300px);
  align-items: center;
  gap: 14px;
  padding: 12px 0;
  border-bottom: 1px solid var(--yui-border);
}

.keyboard-binding-row {
  grid-template-columns: minmax(180px, 1fr) minmax(240px, 360px) auto;
}

.desktop-input-select {
  width: 100%;
}

.keyboard-binding-list {
  display: flex;
  flex-direction: column;
}

.resource-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.resource-download-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  border-block: 1px solid var(--yui-border);
}

.resource-download-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  min-width: 0;
}

.resource-download-options :deep(.el-checkbox__label) {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.resource-download-label {
  font-weight: 600;
}

.storage-maintenance {
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px 0;
  border-block: 1px solid var(--yui-border);
}

.storage-maintenance-header,
.storage-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.storage-summary {
  justify-content: flex-end;
}

.storage-table {
  width: 100%;
}

.storage-no-action {
  color: var(--yui-muted);
  font-size: 12px;
}

.resource-progress-list {
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
}

.resource-progress-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 2fr) auto;
  min-height: 24px;
  gap: 12px;
  align-items: center;
}

.resource-progress-header {
  display: flex;
  min-width: 0;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}

.resource-progress-header span,
.resource-progress-bytes {
  color: var(--yui-muted);
  font-size: 12px;
  white-space: nowrap;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

@media (max-width: 860px) {
  .resource-progress-row {
    grid-template-columns: 1fr;
    gap: 6px;
  }
}

.resource-card {
  min-width: 0;
}

.resource-details {
  display: grid;
  gap: 12px;
}

.resource-details strong {
  display: block;
  margin-bottom: 4px;
  color: var(--yui-text);
  font-size: 13px;
}

.resource-path {
  display: block;
  overflow-wrap: anywhere;
  padding: 8px 10px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  font-size: 12px;
}

.resource-list {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.6;
}

.resource-actions {
  flex-wrap: wrap;
}

.settings-json,
.table-json {
  overflow: auto;
  margin: 10px 0;
  padding: 10px;
  border-radius: var(--yui-radius-card);
  background: #0f172a;
  color: #e2e8f0;
}

:deep(.el-tabs--border-card) {
  overflow: hidden;
  border-color: var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface);
  box-shadow: none;
}

:deep(.el-tabs__nav-wrap) {
  padding-inline: 6px;
}

:deep(.el-tabs__nav-scroll) {
  overflow-x: auto;
  scrollbar-width: none;
}

:deep(.el-tabs__nav-scroll::-webkit-scrollbar) {
  display: none;
}

:deep(.el-card) {
  border-color: var(--yui-border);
  border-radius: 8px;
  box-shadow: none;
}

:deep(.el-card__header) {
  padding: 11px 14px;
}

:deep(.el-card__body) {
  padding: 13px 14px;
}

:deep(.el-button) {
  border-radius: 8px;
  font-weight: 650;
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper),
:deep(.el-input-number .el-input__wrapper) {
  border-radius: 8px;
}

:deep(.el-form-item) {
  margin-bottom: 12px;
}

:deep(.el-tabs__content) {
  padding: 12px;
}

:deep(.el-collapse) {
  border: 0;
}

:deep(.el-collapse-item__header),
:deep(.el-collapse-item__wrap) {
  border-color: var(--yui-border);
  background: transparent;
}

:deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

.table-json {
  max-height: 120px;
}

@media (max-width: 960px) {
  .form-grid,
  .form-grid.three,
  .llm-workspace,
  .voice-workspace,
  .parameter-strip,
  .resource-grid {
    grid-template-columns: 1fr;
  }

  .desktop-input-row,
  .keyboard-binding-row {
    grid-template-columns: 1fr;
  }

  .card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .llm-toolbar,
  .llm-status-strip,
  .tts-toolbar,
  .tts-status-strip,
  .llm-actions {
    align-items: flex-start;
    justify-content: flex-start;
  }

  .llm-action-group + .llm-action-group {
    margin-left: 0;
  }

  .access-row,
  .access-controls {
    align-items: stretch;
    flex-direction: column;
  }

  .access-controls,
  .admin-token-input {
    width: 100%;
    max-width: none;
  }

  .storage-maintenance-header,
  .storage-summary {
    align-items: stretch;
    flex-direction: column;
  }
}

@media (max-width: 520px) {
  :deep(.el-tabs__content),
  :deep(.el-card__body) {
    padding: 8px;
  }

  .resource-download-bar {
    align-items: stretch;
    flex-direction: column;
  }

  .resource-download-options {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 10px;
  }

  .resource-download-bar :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }

  .llm-main-form,
  .voice-main-form {
    padding: 0;
    border: 0;
    background: transparent;
  }

  .tts-runtime-panel {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 9px 12px;
    padding: 8px;
  }

  .tts-runtime-item strong {
    overflow: visible;
    text-overflow: clip;
  }
}
</style>
