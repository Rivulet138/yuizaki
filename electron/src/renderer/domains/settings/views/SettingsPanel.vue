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
          v-if="(saveBusy || saveError || lastSavedAt) && !failedSavePatch"
          :title="saveStatusLabel"
          :description="saveStatusDetail"
          :type="saveStatusType"
          show-icon
          :closable="false"
        />
        <el-alert
          v-if="failedSavePatch"
          :title="t(settingsReadbackFailed ? 'settings.status.readbackFailed' : 'settings.status.saveFailed')"
          :description="t(settingsReadbackFailed ? 'settings.messages.readbackFailed' : 'settings.status.retrySaveDetail')"
          type="error"
          show-icon
          :closable="false"
        >
          <template #default>
            <el-button type="danger" plain size="small" :loading="saveBusy" @click="retryFailedSave">
              {{ t('settings.status.retrySave') }}
            </el-button>
          </template>
        </el-alert>

        <SettingsRuntimeFeedback
          :status="runtimeReload"
          :status-error="runtimeStatusRequest.error || ''"
          :retry-error="runtimeRetryRequest.error || ''"
          :loading="runtimeStatusRequest.loading || runtimeRetryRequest.loading || saveBusy"
          @refresh="refreshRuntimeApplication"
          @retry="retryRuntimeApplication"
        />

        <div class="settings-workspace">
          <nav
            class="settings-section-nav"
            role="tablist"
            :aria-label="t('settings.sectionNav')"
          >
            <section v-for="group in settingSectionGroups" :key="group.id" class="settings-section-group">
              <span class="settings-section-group-label">{{ group.label }}</span>
              <button
                v-for="item in group.items"
                :key="item.id"
                type="button"
                class="settings-section-button"
                role="tab"
                :class="{ active: activeSection === item.id }"
                :aria-selected="activeSection === item.id"
                :aria-controls="`pane-${item.id}`"
                :aria-current="activeSection === item.id ? 'page' : undefined"
                @click="activeSection = item.id"
              >
                {{ item.label }}
              </button>
            </section>
          </nav>

          <el-tabs v-model="activeSection" class="settings-content-tabs">
          <el-tab-pane :label="t('settings.tabs.access')" name="access" lazy>
            <SettingsAccessSection
              v-model:backend-token="backendTokenInput"
              :backend-token-configured="backendTokenConfigured"
              :backend-token-busy="backendTokenBusy"
              :backend-token-status-known="Boolean(backendTokenStatus)"
              :backend-token-source-label="backendTokenSourceLabel"
              :backend-token-preview="backendTokenPreview"
              :backend-token-requires-restart="backendTokenRequiresRestart"
              @save-backend-token="saveBackendToken"
              @reset-backend-token="resetBackendToken"
            />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.llm')" name="llm" lazy>
            <el-card class="llm-settings-card" shadow="never">
              <template #header>
                <div class="card-header">
                  <div class="header-title">
                    <span>{{ t('settings.llm.service') }}</span>
                  </div>
                  <div class="llm-toolbar">
                    <div class="llm-status-strip">
                      <el-tag :type="hasLlmApiKey ? 'success' : 'info'">{{ llmApiKeyTagLabel }}</el-tag>
                      <el-tag :type="llmRuntimeTagType">{{ llmRuntimeLabel }}</el-tag>
                    </div>
                    <div class="llm-actions">
                      <div class="llm-action-group">
                        <el-button plain :loading="llmModelsRequest.loading" :disabled="!canRequestLlmModels" @click="discoverLlmModels({ forceAutoSelect: true, manual: true })">
                          <el-icon><Refresh /></el-icon>
                          {{ t('settings.llm.detectModels') }}
                        </el-button>
                        <el-button plain :loading="llmStatusRequest.loading" @click="refreshLlmStatus">
                          <el-icon><Refresh /></el-icon>
                          {{ t('settings.llm.refreshStatus') }}
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
              <el-form label-position="top" @submit.prevent>
                <div class="llm-workspace">
                  <aside class="llm-profile-rail">
                    <div class="profile-rail-head">
                      <strong>{{ t('settings.llm.profileTitle') }}</strong>
                    </div>
                    <div class="provider-stack" role="radiogroup" :aria-label="t('settings.llm.providerPreset')">
                      <button
                        v-for="option in llmProviderOptionRows"
                        :key="option.value"
                        class="provider-option"
                        :class="{ 'is-active': option.value === llmProviderPreset }"
                        type="button"
                        role="radio"
                        :aria-checked="option.value === llmProviderPreset"
                        :aria-label="`${option.label}: ${option.status}`"
                        @click="applyLlmProviderPreset(option.value)"
                      >
                        <span class="provider-option-label">
                          <strong>{{ option.label }}</strong>
                          <small :class="`status-${option.statusClass}`">{{ option.status }}</small>
                        </span>
                      </button>
                    </div>
                    <el-button class="profile-reset-button" plain @click="resetCurrentLlmProfile">
                      <el-icon><Refresh /></el-icon>
                      {{ t('settings.llm.resetProfile') }}
                    </el-button>
                  </aside>

                  <div class="llm-main-form">
                    <div class="subsection-title">{{ t('settings.llm.sectionConnection') }}</div>
                    <div class="form-grid">
                      <el-form-item :label="t('settings.llm.baseUrl')">
                        <el-input v-model="form.llm.base_url" name="llm-base-url" @change="handleLlmEndpointChange('base_url', $event)" @keyup.enter="scheduleLlmModelDiscovery" />
                      </el-form-item>
                      <el-form-item v-if="llmProviderNeedsApiKey" :label="t('settings.llm.apiKeyLabel')">
                        <el-input
                          v-model="form.llm.api_key"
                          :disabled="isSensitiveDeleting('llm.api_key')"
                          type="password"
                          show-password
                          :placeholder="llmApiKeyPlaceholder"
                          @focus="handleLlmApiKeyFocus"
                          @change="handleLlmEndpointChange('api_key', $event)"
                          @keyup.enter="scheduleLlmModelDiscovery"
                        >
                          <template #append>
                            <el-button v-if="llmApiKeyStored" text type="danger" :loading="isSensitiveDeleting('llm.api_key')" :disabled="isSensitiveDeleting('llm.api_key')" @click="clearLlmApiKey">{{ t('settings.llm.apiKeyClear') }}</el-button>
                          </template>
                        </el-input>
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
                        @change="handleLlmModelChange"
                      >
                        <el-option v-for="model in llmModelSelectOptions" :key="model" :label="model" :value="model" />
                      </el-select>
                      <p v-if="llmModelStatusLabel" class="field-hint" :class="{ error: llmModelsRequest.error }">{{ llmModelStatusLabel }}</p>
                    </el-form-item>

                    <SettingsLlmVisionSection
                      :api-key-stored="visionApiKeyStored"
                      :api-key-deleting="isSensitiveDeleting('llm.vision_api_key')"
                      @clear-api-key="clearVisionApiKey"
                      :model-value="llmVisionSettings"
                      :provider-options="llmProviderOptions"
                      @update="applyLlmVisionPatch"
                    />

                    <div class="inference-title-row"><div class="subsection-title">{{ t('settings.llm.sectionSampling') }}</div><el-button size="small" plain @click="applyRecommendedLlmSettings">{{ t('settings.llm.applyRecommended') }}</el-button></div>
                    <div class="inference-layout">
                      <section v-if="llmGenerationCapabilities.parameters.temperature || llmGenerationCapabilities.parameters.top_p" class="inference-group">
                        <h3 class="inference-group-title">{{ t('settings.llm.sectionGeneration') }}</h3>
                        <div class="inference-fields">
                          <div v-if="llmGenerationCapabilities.parameters.temperature" class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.temperatureName') }}</span>
                              <output>{{ llmParameterValue('temperature').toFixed(2) }}</output>
                            </div>
                            <el-form-item>
                              <el-slider v-if="llmGenerationCapabilities.parameters.temperature!.min < llmGenerationCapabilities.parameters.temperature!.max" :model-value="llmParameterValue('temperature')" @update:model-value="updateLlmParameter('temperature', $event)" :min="llmGenerationCapabilities.parameters.temperature?.min" :max="llmGenerationCapabilities.parameters.temperature?.max" :step="0.1" :aria-label="t('settings.llm.temperatureName')" @change="saveLlmField('temperature', $event)" />
                            </el-form-item>
                          </div>
                          <div v-if="llmGenerationCapabilities.parameters.top_p" class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.topPName') }}</span>
                              <output>{{ llmParameterValue('top_p').toFixed(2) }}</output>
                            </div>
                            <el-form-item>
                              <el-slider v-if="llmGenerationCapabilities.parameters.top_p!.min < llmGenerationCapabilities.parameters.top_p!.max" :model-value="llmParameterValue('top_p')" @update:model-value="updateLlmParameter('top_p', $event)" :min="llmGenerationCapabilities.parameters.top_p?.min" :max="llmGenerationCapabilities.parameters.top_p?.max" :step="0.05" :aria-label="t('settings.llm.topPName')" @change="saveLlmField('top_p', $event)" />
                            </el-form-item>
                          </div>
                        </div>
                      </section>

                      <section v-if="llmGenerationCapabilities.parameters.min_p || llmGenerationCapabilities.parameters.top_k" class="inference-group">
                        <h3 class="inference-group-title">{{ t('settings.llm.sectionFiltering') }}</h3>
                        <div class="inference-fields">
                          <div v-if="llmGenerationCapabilities.parameters.min_p" class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.minPName') }}</span>
                              <output>{{ llmParameterValue('min_p').toFixed(2) }}</output>
                            </div>
                            <el-form-item>
                              <el-slider v-if="llmGenerationCapabilities.parameters.min_p!.min < llmGenerationCapabilities.parameters.min_p!.max" :model-value="llmParameterValue('min_p')" @update:model-value="updateLlmParameter('min_p', $event)" :min="llmGenerationCapabilities.parameters.min_p?.min" :max="llmGenerationCapabilities.parameters.min_p?.max" :step="0.01" :aria-label="t('settings.llm.minPName')" @change="saveLlmField('min_p', $event)" />
                            </el-form-item>
                          </div>
                          <div v-if="llmGenerationCapabilities.parameters.top_k" class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.topKName') }}</span>
                              <output>{{ llmParameterValue('top_k') }}</output>
                            </div>
                            <el-form-item>
                              <el-input-number :model-value="llmParameterValue('top_k')" @update:model-value="updateLlmParameter('top_k', $event)" class="inference-number" :min="0" :max="llmGenerationCapabilities.parameters.top_k?.max" :step="1" controls-position="right" :aria-label="t('settings.llm.topKName')" @change="saveLlmField('top_k', $event)" />
                            </el-form-item>
                          </div>
                        </div>
                      </section>

                      <section v-if="llmGenerationCapabilities.parameters.frequency_penalty || llmGenerationCapabilities.parameters.presence_penalty || llmGenerationCapabilities.parameters.repetition_penalty" class="inference-group inference-group-repetition">
                        <h3 class="inference-group-title">{{ t('settings.llm.sectionRepetition') }}</h3>
                        <div class="inference-fields">
                          <div v-if="llmGenerationCapabilities.parameters.frequency_penalty" class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.frequencyPenaltyName') }}</span>
                              <output>{{ llmParameterValue('frequency_penalty').toFixed(2) }}</output>
                            </div>
                            <el-form-item>
                              <el-slider v-if="llmGenerationCapabilities.parameters.frequency_penalty!.min < llmGenerationCapabilities.parameters.frequency_penalty!.max" :model-value="llmParameterValue('frequency_penalty')" @update:model-value="updateLlmParameter('frequency_penalty', $event)" :min="llmGenerationCapabilities.parameters.frequency_penalty?.min" :max="llmGenerationCapabilities.parameters.frequency_penalty?.max" :step="0.05" :aria-label="t('settings.llm.frequencyPenaltyName')" @change="saveLlmField('frequency_penalty', $event)" />
                            </el-form-item>
                          </div>
                          <div v-if="llmGenerationCapabilities.parameters.presence_penalty" class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.presencePenaltyName') }}</span>
                              <output>{{ llmParameterValue('presence_penalty').toFixed(2) }}</output>
                            </div>
                            <el-form-item>
                              <el-slider v-if="llmGenerationCapabilities.parameters.presence_penalty!.min < llmGenerationCapabilities.parameters.presence_penalty!.max" :model-value="llmParameterValue('presence_penalty')" @update:model-value="updateLlmParameter('presence_penalty', $event)" :min="llmGenerationCapabilities.parameters.presence_penalty?.min" :max="llmGenerationCapabilities.parameters.presence_penalty?.max" :step="0.05" :aria-label="t('settings.llm.presencePenaltyName')" @change="saveLlmField('presence_penalty', $event)" />
                            </el-form-item>
                          </div>
                          <div v-if="llmGenerationCapabilities.parameters.repetition_penalty" class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.repetitionPenaltyName') }}</span>
                              <output>{{ llmParameterValue('repetition_penalty').toFixed(2) }}</output>
                            </div>
                            <el-form-item>
                              <el-slider v-if="llmGenerationCapabilities.parameters.repetition_penalty!.min < llmGenerationCapabilities.parameters.repetition_penalty!.max" :model-value="llmParameterValue('repetition_penalty')" @update:model-value="updateLlmParameter('repetition_penalty', $event)" :min="llmGenerationCapabilities.parameters.repetition_penalty?.min" :max="llmGenerationCapabilities.parameters.repetition_penalty?.max" :step="0.05" :aria-label="t('settings.llm.repetitionPenaltyName')" @change="saveLlmField('repetition_penalty', $event)" />
                            </el-form-item>
                          </div>
                        </div>
                      </section>

                      <section class="inference-group inference-group-limits">
                        <h3 class="inference-group-title">{{ t('settings.llm.sectionLimits') }}</h3>
                        <div class="inference-fields">
                          <div class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.contextTokensName') }}</span>
                              <output>{{ form.llm.context_max_tokens }}</output>
                            </div>
                            <el-form-item>
                              <el-input-number v-model="form.llm.context_max_tokens" class="inference-number" :min="1000" :max="2000000" :step="1000" controls-position="right" :aria-label="t('settings.llm.contextTokensName')" @change="saveLlmField('context_max_tokens', $event)" />
                            </el-form-item>
                          </div>
                          <div class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.maxOutputTokensName') }}</span>
                              <output>{{ form.llm.default_max_output_tokens }}</output>
                            </div>
                            <el-form-item>
                              <el-input-number v-model="form.llm.default_max_output_tokens" class="inference-number" :min="256" :max="128000" :step="256" controls-position="right" :aria-label="t('settings.llm.maxOutputTokensName')" @change="saveLlmField('default_max_output_tokens', $event)" />
                            </el-form-item>
                          </div>
                          <div class="inference-field">
                            <div class="inference-field-head">
                              <span>{{ t('settings.llm.timeoutName') }}</span>
                              <output>{{ form.llm.timeout }}</output>
                            </div>
                            <el-form-item>
                              <el-input-number v-model="form.llm.timeout" class="inference-number" :min="10" :max="300" controls-position="right" :aria-label="t('settings.llm.timeoutName')" @change="saveLlmField('timeout', $event)" />
                            </el-form-item>
                          </div>
                        </div>
                      </section>
                    </div>
                  </div>
                </div>
              </el-form>
            </el-card>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.tts')" name="voice" lazy>
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
                      <el-button plain :loading="genieCharactersRequest.loading" @click="loadGenieCharacters">
                        <el-icon><Connection /></el-icon>
                        {{ t('settings.tts.detectCharacters') }}
                      </el-button>
                      <el-button plain :loading="warmupTtsRequest.loading" :disabled="!hasTtsVoice" @click="handleWarmupTts">
                        <el-icon><Refresh /></el-icon>
                        {{ t('settings.tts.warmup') }}
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
                  <details v-if="ttsStatus || ttsStatusRequest.loading || ttsStatusRequest.error" class="tts-runtime-details">
                    <summary>{{ t('settingsPanel.ttsRuntimeDetails') }}</summary>
                    <div class="tts-runtime-panel">
                      <div v-for="item in ttsRuntimeMetricItems" :key="item.label" class="tts-runtime-item">
                        <span>{{ item.label }}</span>
                        <strong>{{ item.value }}</strong>
                        <small v-if="item.detail">{{ item.detail }}</small>
                      </div>
                    </div>
                  </details>
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
                    <el-form-item :label="t('settings.tts.provider')">
                      <el-select v-model="form.tts.provider" class="full-width" @change="saveTtsField('provider', $event, { flush: true })">
                        <el-option :label="t('settings.tts.provider.genie')" value="genie-tts" />
                        <el-option :label="t('settings.tts.provider.openai')" value="openai-compatible" />
                      </el-select>
                    </el-form-item>
                    <template v-if="form.tts.provider === 'openai-compatible'">
                      <el-form-item :label="t('settings.tts.baseUrl')">
                        <el-input v-model="form.tts.base_url" @input="saveTtsField('base_url', $event)" @change="flushTtsSave" />
                      </el-form-item>
                      <el-form-item :label="t('settings.tts.apiKey')">
                        <el-input v-model="form.tts.api_key" :disabled="isSensitiveDeleting('tts.api_key')" type="password" show-password autocomplete="off" @input="saveTtsField('api_key', $event)" @change="flushTtsSave">
                          <template #append>
                            <el-button v-if="form.tts.api_key || ttsApiKeyStored" text type="danger" :loading="isSensitiveDeleting('tts.api_key')" :disabled="isSensitiveDeleting('tts.api_key')" @click="clearTtsApiKey">{{ t('settings.apiKeyClear') }}</el-button>
                          </template>
                        </el-input>
                      </el-form-item>
                      <el-form-item :label="t('settings.tts.model')">
                        <el-input v-model="form.tts.model" @input="saveTtsField('model', $event)" @change="flushTtsSave" />
                      </el-form-item>
                      <el-form-item :label="t('settings.tts.voice')">
                        <el-input v-model="form.tts.voice" @input="saveTtsField('voice', $event)" @change="flushTtsSave" />
                      </el-form-item>
                      <el-form-item :label="t('settings.tts.timeout')">
                        <el-input-number v-model="form.tts.timeout" :min="1" :max="300" @change="saveTtsField('timeout', $event, { flush: true })" />
                      </el-form-item>
                    </template>
                  </div>
                  <div class="form-grid">
                    <el-form-item :label="t('settings.tts.character')">
                      <el-select
                        v-model="form.tts.genie_character"
                        class="full-width"
                        filterable
                        allow-create
                        default-first-option
                        @change="selectGenieCharacter"
                      >
                        <el-option
                          v-for="character in genieCharacters"
                          :key="character.id"
                          :label="genieCharacterOptionLabel(character)"
                          :value="character.id"
                        />
                      </el-select>
                      <el-alert
                        v-if="selectedGenieCharacter && !selectedGenieCharacter.ready"
                        class="tts-character-resource-alert"
                        :title="selectedGenieCharacter.details.join(', ')"
                        type="warning"
                        :closable="false"
                        show-icon
                      />
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
                        <el-option :label="t('settings.tts.quality.qualityFirst')" :value="TTS_CONTRACT_VALUES.qualityFirst" />
                        <el-option :label="t('settings.tts.quality.speedFirst')" :value="TTS_CONTRACT_VALUES.speedFirst" />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.split')">
                      <el-select v-model="form.tts.split" class="full-width" @change="saveTtsField('split', $event, { flush: true })">
                        <el-option :label="t('settings.tts.split.smart')" :value="TTS_CONTRACT_VALUES.splitSmart" />
                        <el-option :label="t('settings.tts.split.disabled')" :value="TTS_CONTRACT_VALUES.splitDisabled" />
                      </el-select>
                    </el-form-item>
                    <el-form-item :label="t('settings.tts.mode')">
                      <el-select v-model="form.tts.mode" class="full-width" @change="saveTtsField('mode', $event, { flush: true })">
                        <el-option :label="t('settings.tts.mode.serial')" :value="TTS_CONTRACT_VALUES.modeSerial" />
                      </el-select>
                    </el-form-item>
                  </div>
                </div>
              </el-form>
            </el-card>
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.asr')" name="asr" lazy>
            <SettingsAsrSection
              :model-value="form.asr"
              :api-key-stored="asrApiKeyStored"
              :api-key-deleting="isSensitiveDeleting('asr.api_key')"
              :discovery-loading="localDiscoveryRequest.loading"
              :discovery-error="localDiscoveryRequest.error"
              @discover-local="applyLocalAsrDiscovery"
              @update-field="saveAsrField"
              @clear-api-key="clearAsrApiKey"
            />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.memory')" name="memory" lazy>
            <SettingsMemorySection
              :model-value="form.memory"
              :api-key-stored="memoryApiKeyStored"
              :api-key-deleting="isSensitiveDeleting('memory.qdrant_api_key')"
              :discovery-loading="localDiscoveryRequest.loading"
              :index-status="memoryIndexStatus"
              :index-status-loading="memoryIndexStatusLoading"
              :index-status-error="memoryIndexStatusError"
              @refresh-status="refreshMemoryIndexStatus"
              :rebuild-loading="memoryIndexWorking"
              :rebuild-job="memoryRebuildJob"
              :rebuild-error="memoryRebuildError"
              :rebuild-refreshing="memoryRebuildRefreshing"
              :rebuild-cancelling="memoryRebuildCancelling"
              @refresh-rebuild="refreshMemoryRebuild"
              @cancel-rebuild="cancelMemoryRebuild"
              :default-embedding-model="DEFAULT_EMBEDDING_MODEL"
              :default-qdrant-docker-image="DEFAULT_QDRANT_DOCKER_IMAGE"
              @change-backend="handleMemoryBackendChange"
              @update-field="saveMemoryField"
              @clear-api-key="clearMemoryApiKey"
              @discover-local="applyLocalMemoryDiscovery"
              @rebuild="handleRebuildMemoryIndex"
            />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.summary')" name="summary" lazy>
            <SettingsSummarySection :model-value="form.summary" @update-field="saveSummaryField" />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.svc')" name="svc" lazy>
            <SettingsSvcSection
              :model-value="form.svc"
              :discovery-loading="localDiscoveryRequest.loading"
              :discovery-error="localDiscoveryRequest.error"
              :test-loading="testSvcRequest.loading"
              :before-action="flushPendingSave"
              :test-result="svcTestResult"
              @discover-local="applyLocalSvcDiscovery"
              @open-service="openServiceSettings"
              @test-service="handleTestSvc"
              @reset="resetSvcSettings"
              @update-field="saveSvcField"
            />
          </el-tab-pane>

          <el-tab-pane :label="t('settings.tabs.resources')" name="resources" lazy>
            <SettingsResourcesSection
              :resource-message="resourceMessage"
              :resource-message-type="resourceMessageType"
              :resource-loading="resourceLoading"
              :storage-loading="storageLoading"
              :cancellable-resource-ids="cancellableResourceIds"
              :resource-cancel-loading="resourceCancelLoading"
              :active-download-progress="activeDownloadProgress"
              :resource-view="resourceView"
              :selected-resource-ids="selectedResourceIds"
              :resource-download-options="resourceDownloadOptions"
              :storage-status="storageStatus"
              :resource-action-key="resourceActionKey"
              :storage-action-key="storageActionKey"
              @refresh="refreshResourcePanel"
              @cancel-downloads="cancelActiveResourceDownloads"
              @update:selected-resource-ids="selectedResourceIds = $event"
              @download-selected="downloadSelectedResources"
              @prepare-resource="prepareResource"
              @import-soulx-reference="importSoulxReference"
              @remove-resource="removeModelResource"
              @cleanup-storage="cleanupStorage"
              @cleanup-all="cleanupAllStorage"
            />
          </el-tab-pane>
          <el-tab-pane :label="t('settings.tabs.system')" name="system" lazy>
            <SettingsInterfaceSection
              :model-value="form.system"
              :theme-options="themeOptions"
              :language-options="languageOptions"
              @change-theme="handleSystemThemeChange"
              @change-language="handleSystemLanguageChange"
            />

            <SettingsDesktopInputSection
              :state="inputBindingState"
              @reset="resetDesktopInputBindings"
              @set-browser-shortcuts-enabled="setBrowserShortcutsEnabled"
              @set-push-to-talk-enabled="setPushToTalkEnabled"
              @set-push-to-talk-mouse-button="setPushToTalkMouseButton"
              @capture-keyboard="captureKeyboardBinding"
              @clear-keyboard="clearKeyboardBinding"
              @set-keyboard="setKeyboardBinding"
              @retry="retryDesktopInputBindings"
            />

            <el-card class="settings-admin-card" shadow="never">
              <template #header>{{ t('settings.admin.title') }}</template>
              <el-collapse v-model="adminCollapseNames">
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
                  <el-form-item :label="t('settings.key.valueMode')">
                    <el-select v-model="setValueMode">
                      <el-option :label="t('settings.key.jsonMode')" value="json" />
                      <el-option :label="t('settings.key.stringMode')" value="string" />
                    </el-select>
                  </el-form-item>
                  <el-form-item :label="t('settings.key.value')">
                    <el-input v-model="setValueJson" type="textarea" :rows="2" :placeholder="setValueMode === 'json' ? '&quot;dark&quot; / 42 / {&quot;enabled&quot;:true}' : t('settings.key.stringPlaceholder')" />
                  </el-form-item>
                  <el-alert v-if="keyError" :title="keyError" type="error" show-icon :closable="false" />
                  <pre v-if="lookupResult" class="settings-json">{{ lookupResult }}</pre>
                  <div class="button-row">
                    <el-button type="warning" plain :loading="keyOperation === 'rollback'" :disabled="Boolean(keyOperation)" @click="rollbackSettings">{{ t('common.rollback') }}</el-button>
                    <el-button plain :loading="keyOperation === 'read'" :disabled="Boolean(keyOperation) || !lookupKey.trim()" @click="readSettingKey">{{ t('common.read') }}</el-button>
                    <el-button type="primary" plain :loading="keyOperation === 'write'" :disabled="Boolean(keyOperation) || !setKey.trim() || (setValueMode === 'json' && !setValueJson.trim())" @click="writeSettingKey">{{ t('common.write') }}</el-button>
                    <el-button type="danger" plain :loading="keyOperation === 'reset'" :disabled="Boolean(keyOperation) || !deleteKey.trim()" @click="resetSettingKey">{{ t('common.delete') }}</el-button>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </el-card>
          </el-tab-pane>
          <el-tab-pane :label="t('settings.tabs.runtimeGuide')" name="runtime-guide" lazy>
            <section class="runtime-guide-section" aria-labelledby="runtime-guide-title">
              <h2 id="runtime-guide-title">{{ t('settings.runtimeGuide.title') }}</h2>
              <el-button type="primary" plain @click="openOnboarding">
                {{ t('settings.runtimeGuide.open') }}
              </el-button>
            </section>
          </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </AsyncState>
  </PanelShell>
</template>

<script setup lang="ts">
import { ElAlert, ElIcon } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/icon/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElSlider } from 'element-plus'
import 'element-plus/es/components/slider/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { ElTag } from 'element-plus'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import 'element-plus/es/components/tag/style/css'
import { computed, onActivated, onDeactivated, onBeforeUnmount, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElCollapse, ElCollapseItem, ElForm, ElFormItem, ElMessage, ElMessageBox, ElOption, ElSelect, ElTabPane, ElTable, ElTableColumn, ElTabs } from 'element-plus'
import 'element-plus/es/components/table/style/css'
import 'element-plus/es/components/table-column/style/css'
import 'element-plus/es/components/collapse/style/css'
import 'element-plus/es/components/collapse-item/style/css'
import 'element-plus/es/components/tabs/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/tab-pane/style/css'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { Connection, Refresh } from '@element-plus/icons-vue'
import { currentLocale, localeLabel, normalizeLocale, setLocale, supportedLocales, t } from '@/i18n'
import { settingsPanelTtsTokens as TTS_CONTRACT_VALUES } from '@/i18n/settingsPanelMessages'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import AsyncState from '@/shared/components/feedback/AsyncState.vue'
import { useDomainRequest } from '@/shared/composables/useDomainRequest'
import { useSettingsStore } from '@/state/settingsStore'
import {
  DEFAULT_LLM_CONTEXT_MAX_TOKENS,
  DEFAULT_LLM_MAX_OUTPUT_TOKENS,
  DEFAULT_LLM_TEMPERATURE,
  DEFAULT_LLM_TOP_P,
  DEFAULT_LLM_TOP_K,
  DEFAULT_LLM_MIN_P,
  DEFAULT_LLM_FREQUENCY_PENALTY,
  DEFAULT_LLM_PRESENCE_PENALTY,
  DEFAULT_LLM_REPETITION_PENALTY,
  DEFAULT_LLM_TIMEOUT_SECONDS,
  DEFAULT_QDRANT_DOCKER_IMAGE,
} from '@/../shared/runtime-defaults'
import { normalizeGenerationValue, resolveGenerationCapabilities, type GenerationParameter } from '@/../shared/llm-generation-parameters'
import { useInputBindingsStore } from '@/state/inputBindingsStore'
import { settingsClient, type BackendTokenMutationResponse, type BackendTokenStatusResponse, type GenieCharacterResource, type GenieCharacterResourcesResponse, type LocalRuntimeCandidate, type LocalRuntimeDiscoveryResponse, type TtsRuntimeStatusResponse, type SettingsMutationResponse, type SettingsResponse } from '@/api/clients/settings-client'
import { resourceClient } from '@/api/clients/resource-client'
import { parseSettingInput, restoreLaterSettingsDraft, settingValueAt, snapshotSettingsDraft, unsentSettingsDraft } from '../settingsDraft'
import { memoryClient, type MemoryIndexRebuildJob, type MemoryIndexStatus } from '@/api/clients/memory-client'
import type { ManagedModelResourceId, ManagedResourceMetadata, ModelResourceStatusPayload, ResumableResourceDownload, ResourceCommandResult, StorageCategoryId, StorageStatusPayload } from '@/../shared/resource-manager'
import { DEFAULT_VAD_MIN_SILENCE_MS } from '@/../shared/runtime-defaults'
import { findKeyboardBindingConflicts, keyboardEventToAccelerator, normalizeKeyboardAccelerator, type InputBindingSettingsPatch, type KeyboardShortcutAction, type MouseSideButton } from '@/../shared/input-bindings'
import { useSettingsDomain } from '../composables/useSettingsDomain'
import { settingsSaveState as saveQueue, settingsPatchFields, selectSettingsFields, acknowledgeSettingsFailures, type SettingsFieldTokens } from '../settingsSaveState'
import SettingsRuntimeFeedback from '../components/SettingsRuntimeFeedback.vue'
import { openOnboarding } from '@/domains/onboarding/onboardingEvents'
import SettingsAsrSection, { type AsrSettings } from '../components/SettingsAsrSection.vue'
import SettingsAccessSection from '../components/SettingsAccessSection.vue'
import SettingsLlmVisionSection from '../components/SettingsLlmVisionSection.vue'
import SettingsMemorySection, { type MemorySettings } from '../components/SettingsMemorySection.vue'
import SettingsSummarySection, { type SummarySettings } from '../components/SettingsSummarySection.vue'
import SettingsSvcSection, { type SvcSettings } from '../components/SettingsSvcSection.vue'
import SettingsDesktopInputSection from '../components/SettingsDesktopInputSection.vue'
import SettingsInterfaceSection from '../components/SettingsInterfaceSection.vue'
import SettingsResourcesSection from '../components/SettingsResourcesSection.vue'
import { isGpt61SolModel, isLocalLlmEndpoint, migrateLegacyLlmDefaults, normalizeOpenAiBaseUrl, shouldAutoDiscoverLlmModels } from '../llmDiscovery'
import { LLM_PROVIDER_BASE_URLS, choosePreferredLlmModel, getLlmProviderOptions, inferLlmProviderPreset } from '../llmProviders'
import type { LlmProviderPreset } from '../llmProviders'
import { isPlainRecord, normalizeResourceStatus, normalizeStorageStatus } from '../resourceStatus'
import { describeFailure } from '@/shared/errors/describe-error'

type SaveTimeout = ReturnType<typeof window.setTimeout>
type SettingSectionId = 'access' | 'llm' | 'voice' | 'asr' | 'memory' | 'summary' | 'svc' | 'resources' | 'system' | 'runtime-guide'
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
type LlmVisionPatch = Partial<{
  enabled: boolean
  provider: LlmProviderPreset
  baseUrl: string
  apiKey: string
  model: string
  timeout: number
  detail: 'low' | 'high' | 'auto' | 'original'
}>
type ProviderStatusClass = 'ready' | 'warning' | 'muted'
const SETTINGS_SECRET_MASK = '********'
type TtsProviderPreset = 'genie-tts' | 'openai-compatible'
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
  base_url: string
  api_key: string
  model: string
  voice: string
  timeout: number
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
  settingsReadbackFailed: localSettingsReadbackFailed,
  runtimeReload,
  runtimeStatusRequest,
  runtimeRetryRequest,
  retryRuntime,
  acceptRuntimeStatus,
  loadRuntimeStatus,
  updateRequest,
  llmModels,
  llmModelsRequest,
  llmStatus,
  llmStatusRequest,
  ttsStatus,
  ttsStatusRequest,
  testLlmRequest,
  testTtsRequest,
  testSvcRequest,
  loadSettings,
  patchSettings,
  loadLlmModels,
  loadLlmStatus,
  loadTtsStatus,
  testLlm,
  testTts,
  testSvc,
  warmupTtsRequest,
  warmupTts,
} = useSettingsDomain()

const genieCharacters = ref<GenieCharacterResource[]>([])
const genieCharactersRequest = useDomainRequest<GenieCharacterResourcesResponse>()

const settingsStore = useSettingsStore()
const route = useRoute()
const inputBindingsStore = useInputBindingsStore()
const inputBindingState = inputBindingsStore.state

const form = reactive({
  llm: {
    provider: 'custom' as LlmProviderPreset,
    base_url: '',
    api_key: '',
    model: '',
    temperature: DEFAULT_LLM_TEMPERATURE,
    top_p: DEFAULT_LLM_TOP_P,
    top_k: DEFAULT_LLM_TOP_K,
    min_p: DEFAULT_LLM_MIN_P,
    frequency_penalty: DEFAULT_LLM_FREQUENCY_PENALTY,
    presence_penalty: DEFAULT_LLM_PRESENCE_PENALTY,
    repetition_penalty: DEFAULT_LLM_REPETITION_PENALTY,
    timeout: DEFAULT_LLM_TIMEOUT_SECONDS,
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
    device: 'cpu' as TtsProfile['device'],
    quality: TTS_CONTRACT_VALUES.qualityFirst,
    split: TTS_CONTRACT_VALUES.splitSmart,
    mode: TTS_CONTRACT_VALUES.modeSerial,
    save_mode: TTS_CONTRACT_VALUES.saveModeDisabled,
    provider: TTS_PROVIDER as TtsProviderPreset,
    base_url: '',
    api_key: '',
    model: 'tts-1',
    voice: 'alloy',
    timeout: 60,
  },
  asr: {
    provider: 'sherpa-onnx',
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
    provider: 'soulx-service' as SvcSettings['provider'],
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
    qdrant_auto_start: false,
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

const settingSectionGroups = computed(() => [
  {
    id: 'connection',
    label: t('settings.groups.connection'),
    items: [
      { id: 'access' as const, label: t('settings.tabs.access') },
      { id: 'llm' as const, label: t('settings.tabs.llm') },
    ],
  },
  {
    id: 'voice',
    label: t('settings.groups.voice'),
    items: [
      { id: 'voice' as const, label: t('settings.tabs.tts') },
      { id: 'asr' as const, label: t('settings.tabs.asr') },
      { id: 'svc' as const, label: t('settings.tabs.svc') },
    ],
  },
  {
    id: 'memory',
    label: t('settings.groups.memory'),
    items: [
      { id: 'memory' as const, label: t('settings.tabs.memory') },
      { id: 'summary' as const, label: t('settings.tabs.summary') },
    ],
  },
  {
    id: 'application',
    label: t('settings.groups.application'),
    items: [
      { id: 'resources' as const, label: t('settings.tabs.resources') },
      { id: 'system' as const, label: t('settings.tabs.system') },
      { id: 'runtime-guide' as const, label: t('settings.tabs.runtimeGuide') },
    ],
  },
])
const activeSection = ref<SettingSectionId>('llm')
const settingSectionIds: SettingSectionId[] = ['access', 'llm', 'voice', 'asr', 'memory', 'summary', 'svc', 'resources', 'system', 'runtime-guide']
const syncSectionFromRoute = () => {
  const requested = Array.isArray(route.query.section) ? route.query.section[0] : route.query.section
  if (typeof requested === 'string' && settingSectionIds.includes(requested as SettingSectionId)) {
    activeSection.value = requested as SettingSectionId
  }
}
const adminCollapseNames = ref<string[]>([])
const lastSavedAt = ref('')
const lastApplied = ref<string[]>([])
const lastRuntimePending = ref<string[]>([])
const SAVE_DEBOUNCE_MS = 350
const SAVE_MAX_WAIT_MS = 1000
let modelDiscoveryTimeout: SaveTimeout | null = null
let modelDiscoveryRun = 0
let lastLlmModelDiscoveryKey = ''
let activeLlmModelDiscoveryKey: string | null = null
let scheduledLlmModelDiscoveryKey: string | null = null
let suppressModelDiscovery = false
const saveOwner = Symbol('settings-panel')
let saveErrorId: symbol | null = null
const pendingSavePatch = saveQueue.pending
const failedSavePatch = saveQueue.failed
const settingsReadbackFailed = saveQueue.readbackFailed
const deletingSensitiveKeys = saveQueue.deletingKeys
const saveInFlight = saveQueue.inFlight
let unmounted = false
const settingsMetadata = ref<Record<string, unknown> | null>(null)
const settingsHistory = ref<Record<string, unknown>[]>([])
const memoryRebuildRequest = useDomainRequest<Awaited<ReturnType<typeof memoryClient.rebuildIndex>>>()
const memoryIndexStatus = ref<MemoryIndexStatus | null>(null)
const memoryIndexStatusLoading = ref(false)
const memoryIndexStatusError = ref('')
let memoryIndexStatusSequence = 0
const memoryRebuildJob = ref<MemoryIndexRebuildJob | null>(null)
const memoryRebuildError = ref('')
const memoryRebuildStarting = ref(false)
const memoryRebuildCancelling = ref(false)
const memoryRebuildRefreshing = ref(false)
const memoryIndexWorking = computed(() => memoryRebuildStarting.value || Boolean(memoryRebuildJob.value && ['queued', 'running', 'cancelling'].includes(memoryRebuildJob.value.state)))
let memoryRebuildPollTimer: ReturnType<typeof window.setTimeout> | null = null
let memoryRebuildPollStartedAt = 0
const rollbackSteps = ref(1)
const deleteKey = ref('')
const lookupKey = ref('')
const lookupResult = ref('')
const setKey = ref('')
const setValueJson = ref('')
const setValueMode = ref<'json' | 'string'>('json')
const keyOperation = ref<'read' | 'write' | 'reset' | 'rollback' | ''>('')
const keyError = ref('')
let keyMutationAcquired = false
const llmModelStatus = ref('')
const llmModelAutoSelected = ref(false)
const backendTokenInput = ref('')
const backendTokenStatus = ref<BackendTokenStatusResponse | null>(null)
const backendTokenStatusRequest = useDomainRequest<BackendTokenStatusResponse>()
const backendTokenMutationRequest = useDomainRequest<BackendTokenMutationResponse>()
const localDiscoveryRequest = useDomainRequest<LocalRuntimeDiscoveryResponse>()
const svcTestResult = ref<{ ok: boolean; message?: string } | null>(null)
const llmProviderPreset = ref<LlmProviderPreset>('custom')
const llmGenerationCapabilities = computed(() => resolveGenerationCapabilities(llmProviderPreset.value, form.llm.model))
const llmParameterValue = (parameter: GenerationParameter) => {
  const value = form.llm[parameter]
  const bounds = llmGenerationCapabilities.value.parameters[parameter]
  return bounds && !(parameter === 'top_k' && value === 0) ? normalizeGenerationValue(value, bounds) : value
}
const updateLlmParameter = (parameter: GenerationParameter, value: unknown) => {
  if (typeof value === 'number' && Number.isFinite(value)) form.llm[parameter] = value
}

const llmProfiles = reactive<LlmProfiles>({})
const llmApiKeyStored = ref(false)
const visionApiKeyStored = ref(false)
const ttsApiKeyStored = ref(false)
const asrApiKeyStored = ref(false)
const memoryApiKeyStored = ref(false)
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
let resourcePollFailures = 0
let resourcePollStartedAt = 0
let resourceStatusVersion = 0
const cancellingResourceIds = ref<ManagedModelResourceId[]>([])
let resourceStateUncertain = false
const RESOURCE_PROGRESS_POLL_INTERVAL_MS = 1000
const storageStatus = ref<StorageStatusPayload | null>(null)
const storageLoading = ref(false)
const storageActionKey = ref('')

const invalidateLlmModelDiscovery = (options: { preserveLast?: boolean } = {}) => {
  modelDiscoveryRun += 1
  activeLlmModelDiscoveryKey = null
  scheduledLlmModelDiscoveryKey = null
  if (!options.preserveLast) lastLlmModelDiscoveryKey = ''
  if (modelDiscoveryTimeout) clearTimeout(modelDiscoveryTimeout)
  modelDiscoveryTimeout = null
  llmModelsRequest.reset()
}

const llmProviderOptions = computed(() => getLlmProviderOptions(t('common.custom')))
const llmVisionSettings = computed(() => ({
  enabled: form.llm.vision_enabled,
  provider: form.llm.vision_provider,
  baseUrl: form.llm.vision_base_url,
  apiKey: form.llm.vision_api_key,
  model: form.llm.vision_model,
  timeout: form.llm.vision_timeout,
  detail: form.llm.vision_detail,
}))
const activeLlmProfileLabel = computed(() => (
  llmProviderOptions.value.find((item) => item.value === llmProviderPreset.value)?.label || t('common.custom')
))
const llmProviderNeedsApiKey = computed(() => llmProfileNeedsApiKey({
  provider: llmProviderPreset.value,
  base_url: form.llm.base_url,
}))
const llmApiKeyTagLabel = computed(() => {
  if (!llmProviderNeedsApiKey.value) return t('settings.llm.apiKeyNotRequired')
  return form.llm.api_key.trim() || llmApiKeyStored.value ? t('settings.llm.apiKeySavedTag') : t('settings.llm.apiKeyMissing')
})
const llmApiKeyPlaceholder = computed(() => llmApiKeyStored.value ? t('settings.llm.apiKeyPlaceholder') : '')

const saveAsrField = (field: keyof AsrSettings, value: string | number) => {
  Object.assign(form.asr, { [field]: value })
  debouncedSave({ asr: { [field]: value } })
}

const clearSettingValue = (target: unknown, key: string) => {
  const [section, field] = key.split('.', 2)
  if (!section || !field || !target || typeof target !== 'object') return
  const sectionValue = (target as Record<string, unknown>)[section]
  if (sectionValue && typeof sectionValue === 'object') {
    ;(sectionValue as Record<string, unknown>)[field] = ''
  }
}

const stripPatchPath = (patch: SettingsPatch | null, fieldPath: string, prefix = ''): SettingsPatch | null => {
  if (!patch) return null
  const next: SettingsPatch = {}
  for (const [key, value] of Object.entries(patch)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (path === fieldPath) continue
    if (isPlainRecord(value)) {
      const child = stripPatchPath(value, fieldPath, path)
      if (child && Object.keys(child).length) next[key] = child
      continue
    }
    next[key] = value
  }
  return Object.keys(next).length ? next : null
}

const stripDeletingSensitiveKeys = (patch: SettingsPatch | null): SettingsPatch | null => {
  let next = patch
  for (const key of deletingSensitiveKeys.value) {
    next = stripPatchPath(next, key)
  }
  return next
}

const setSensitiveDeleting = (key: string, deleting: boolean) => {
  const next = new Set(deletingSensitiveKeys.value)
  if (deleting) next.add(key)
  else next.delete(key)
  deletingSensitiveKeys.value = next
}

const isSensitiveDeleting = (key: string) => deletingSensitiveKeys.value.has(key)

const clearDeletedCredentialDraft = (key: string) => {
  clearSettingValue(form, key)
  if (key === 'llm.api_key') {
    llmApiKeyStored.value = false
    for (const profile of Object.values(llmProfiles)) profile.api_key = ''
  }
  if (key === 'llm.vision_api_key') visionApiKeyStored.value = false
  if (key === 'tts.api_key') ttsApiKeyStored.value = false
  if (key === 'asr.api_key') asrApiKeyStored.value = false
  if (key === 'memory.qdrant_api_key') memoryApiKeyStored.value = false
}

const publishCredentialDeletion = (key: string) => {
  const normalized = snapshotSettingsDraft(settings.value || settingsStore.state)
  clearSettingValue(normalized, key)
  if (key === 'llm.api_key') {
    for (const profile of Object.values(normalized.llm.profiles || {})) profile.api_key = ''
  }
  const recoveredFailures = acknowledgeSettingsFailures([JSON.stringify(key.split('.'))])
  saveQueue.completion.value = { status: 'ok', normalizedSettings: normalized, submitted: {}, owner: saveOwner, deletedKeys: [key], recoveredFailures }
  finishSubmission(new Map(), recoveredFailures)
}

const clearSensitiveSetting = async (key: string, clearLocal: () => void) => {
  if (deletingSensitiveKeys.value.has(key)) return
  setSensitiveDeleting(key, true)
  pendingSavePatch.value = stripPatchPath(pendingSavePatch.value, key)
  failedSavePatch.value = stripPatchPath(failedSavePatch.value, key)
  let acquired = false
  try {
    acquired = await beginSettingsMutation()
    if (!acquired) return
    await settingsClient.deleteSetting(key)
    publishCredentialDeletion(key)
    clearLocal()
    clearSettingValue(settingsStore.state, key)
    clearSettingValue(settings.value, key)
    pendingSavePatch.value = stripPatchPath(pendingSavePatch.value, key)
    failedSavePatch.value = stripPatchPath(failedSavePatch.value, key)
    ElMessage.success(t('settings.apiKeyCleared'))
  } catch (error) {
    ElMessage.error(describeFailure(error, t('common.error.unknown')))
  } finally {
    if (acquired) finishSettingsMutation()
    setSensitiveDeleting(key, false)
  }
}

const clearVisionApiKey = () => clearSensitiveSetting('llm.vision_api_key', () => {
  form.llm.vision_api_key = ''
  visionApiKeyStored.value = false
})

const clearTtsApiKey = () => clearSensitiveSetting('tts.api_key', () => {
  form.tts.api_key = ''
  ttsApiKeyStored.value = false
})

const clearAsrApiKey = () => clearSensitiveSetting('asr.api_key', () => {
  form.asr.api_key = ''
  asrApiKeyStored.value = false
})

const clearMemoryApiKey = () => clearSensitiveSetting('memory.qdrant_api_key', () => {
  form.memory.qdrant_api_key = ''
  memoryApiKeyStored.value = false
})

const saveMemoryField = (field: keyof MemorySettings, value: MemorySettings[keyof MemorySettings]) => {
  Object.assign(form.memory, { [field]: value })
  debouncedSave({ memory: { [field]: value } })
}
const saveSummaryField = (field: keyof SummarySettings, value: number | string) => {
  Object.assign(form.summary, { [field]: value })
  debouncedSave({ summary: { [field]: value } })
}
const activeTtsProviderLabel = computed(() => form.tts.provider === 'openai-compatible'
  ? t('settings.tts.provider.openai')
  : t('settings.tts.genieProvider'))
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
const serviceApplicationHint = (section: string): string => {
  const status = runtimeReload.value?.sections[section]
  if (!status || status.state === 'applied') return ''
  return t(status.state === 'failed' || status.state === 'unavailable' ? 'settings.status.serviceFailed' : 'settings.status.servicePending')
}
const serviceApplicationTag = (section: string): TagType | null => {
  const status = runtimeReload.value?.sections[section]
  if (!status || status.state === 'applied') return null
  return status.state === 'failed' || status.state === 'unavailable' ? 'danger' : 'warning'
}
const ttsRuntimeError = computed(() => ttsStatusRequest.error || ttsStatus.value?.last_error || '')
const ttsRuntimeLabel = computed(() => {
  if (serviceApplicationHint('tts')) return serviceApplicationHint('tts')
  const snapshot = ttsStatus.value
  if (ttsStatusRequest.loading) return t('settings.tts.status.refreshing')
  if (ttsStatusRequest.error) return t('settings.tts.status.unreadable')
  if (!snapshot) return t('settings.tts.status.unread')
  if ((snapshot.provider && snapshot.provider !== form.tts.provider)
    || (form.tts.provider === 'genie-tts' && snapshot.character && snapshot.character !== form.tts.genie_character)) return t('settings.tts.status.configChanged')
  if (snapshot.loading) return t('settings.tts.status.loading')
  if (snapshot.warmup_running || snapshot.warming_up) return t('settings.tts.status.warming')
  if (snapshot.inference_running) return t('settings.tts.status.synthesizing')
  if (snapshot.warmup_done) return t('settings.tts.status.ready')
  if (snapshot.available) return t('settings.tts.status.loaded')
  return t('settings.tts.status.cold')
})
const ttsRuntimeTagType = computed<TagType>(() => {
  const applicationTag = serviceApplicationTag('tts')
  if (applicationTag) return applicationTag
  const snapshot = ttsStatus.value
  if (ttsStatusRequest.error || snapshot?.last_error) return 'danger'
  if (ttsStatusRequest.loading || snapshot?.loading || snapshot?.warmup_running || snapshot?.warming_up || snapshot?.inference_running) return 'warning'
  if ((snapshot?.provider && snapshot.provider !== form.tts.provider)
    || (form.tts.provider === 'genie-tts' && snapshot?.character && snapshot.character !== form.tts.genie_character)) return 'warning'
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
  temperature: DEFAULT_LLM_TEMPERATURE,
  top_p: DEFAULT_LLM_TOP_P,
  top_k: DEFAULT_LLM_TOP_K,
  min_p: DEFAULT_LLM_MIN_P,
  frequency_penalty: DEFAULT_LLM_FREQUENCY_PENALTY,
  presence_penalty: DEFAULT_LLM_PRESENCE_PENALTY,
  repetition_penalty: DEFAULT_LLM_REPETITION_PENALTY,
  timeout: DEFAULT_LLM_TIMEOUT_SECONDS,
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
  const masked = profile.api_key === SETTINGS_SECRET_MASK
  form.llm.api_key = KEYLESS_LLM_PROVIDERS.has(profile.provider) || masked ? '' : profile.api_key
  llmApiKeyStored.value = !KEYLESS_LLM_PROVIDERS.has(profile.provider) && (masked || Boolean(profile.api_key.trim()))
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

const saveActiveLlmPatch = (patch: SettingsPatch) => {
  const activeProfile = snapshotLlmProfile()
  llmProfiles[activeProfile.provider] = activeProfile
  const profilePatch = Object.fromEntries(Object.entries(patch).filter(([field]) => field !== 'api_key'))
  debouncedSave({ llm: {
    ...patch,
    ...(Object.keys(profilePatch).length ? { profiles: { [activeProfile.provider]: profilePatch } } : {}),
  } })
}

const applyRecommendedLlmSettings = () => {
  const isGpt61Sol = isGpt61SolModel(form.llm.model)
  const numericDefaults: Record<GenerationParameter, number> = {
    temperature: DEFAULT_LLM_TEMPERATURE,
    top_p: DEFAULT_LLM_TOP_P,
    top_k: DEFAULT_LLM_TOP_K,
    min_p: DEFAULT_LLM_MIN_P,
    frequency_penalty: DEFAULT_LLM_FREQUENCY_PENALTY,
    presence_penalty: DEFAULT_LLM_PRESENCE_PENALTY,
    repetition_penalty: DEFAULT_LLM_REPETITION_PENALTY,
  }
  const recommended: Partial<Record<GenerationParameter, number>> & Pick<LlmProfile, 'timeout' | 'context_max_tokens' | 'default_max_output_tokens'> = {
    timeout: DEFAULT_LLM_TIMEOUT_SECONDS,
    context_max_tokens: isGpt61Sol ? 500_000 : DEFAULT_LLM_CONTEXT_MAX_TOKENS,
    default_max_output_tokens: isGpt61Sol ? 16_384 : DEFAULT_LLM_MAX_OUTPUT_TOKENS,
  }
  for (const parameter of Object.keys(numericDefaults) as GenerationParameter[]) {
    const bounds = llmGenerationCapabilities.value.parameters[parameter]
    if (bounds) recommended[parameter] = parameter === 'top_k' ? 0 : normalizeGenerationValue(numericDefaults[parameter], bounds)
  }
  Object.assign(form.llm, recommended)
  saveActiveLlmPatch(recommended)
}

const saveLlmField = (field: LlmProfileField, value: unknown) => {
  if (field === 'api_key' && !llmProviderNeedsApiKey.value) {
    form.llm.api_key = ''
    saveActiveLlmPatch({ api_key: '' })
    return
  }
  saveActiveLlmPatch({ [field]: value })
}

const handleLlmApiKeyFocus = () => {
  if (form.llm.api_key === SETTINGS_SECRET_MASK) form.llm.api_key = ''
}

const clearLlmApiKey = async () => {
  const key = 'llm.api_key'
  if (deletingSensitiveKeys.value.has(key)) return
  setSensitiveDeleting(key, true)
  pendingSavePatch.value = stripPatchPath(pendingSavePatch.value, key)
  failedSavePatch.value = stripPatchPath(failedSavePatch.value, key)
  let acquired = false
  try {
    acquired = await beginSettingsMutation()
    if (!acquired) return
    await settingsClient.deleteSetting(key)
    publishCredentialDeletion(key)
    form.llm.api_key = ''
    llmApiKeyStored.value = false
    for (const profile of Object.values(llmProfiles)) profile.api_key = ''
    clearSettingValue(settingsStore.state, key)
    clearSettingValue(settings.value, key)
    pendingSavePatch.value = stripPatchPath(pendingSavePatch.value, key)
    failedSavePatch.value = stripPatchPath(failedSavePatch.value, key)
    // The DELETE endpoint removes the vault value, but the backend settings
    // document may still contain legacy nested profile keys. Persist the
    // scrubbed profile payload immediately so a later reload cannot restore it.
    finishSettingsMutation()
    acquired = false
    debouncedSave({
      llm: {
        api_key: '',
        profiles: Object.fromEntries(Object.keys(llmProfiles).map((provider) => [provider, { api_key: '' }])),
      },
    })
    if (!(await flushPendingSave())) {
      throw new Error(t('settings.messages.saveFailed'))
    }
    ElMessage.success(t('settings.llm.apiKeyCleared'))
  } catch (error) {
    ElMessage.error(describeFailure(error, t('common.error.unknown')))
  } finally {
    if (acquired) finishSettingsMutation()
    setSensitiveDeleting(key, false)
  }
}

const defaultTtsProfile = (): TtsProfile => {
  return {
    genie_character: '',
    genie_model_dir: '',
    ref_audio: '',
    ref_text: '',
    lang: 'ja',
    device: 'cpu',
    quality: TTS_CONTRACT_VALUES.qualityFirst,
    split: TTS_CONTRACT_VALUES.splitSmart,
    mode: TTS_CONTRACT_VALUES.modeSerial,
    save_mode: TTS_CONTRACT_VALUES.saveModeDisabled,
    provider: TTS_PROVIDER,
    base_url: '',
    api_key: '',
    model: 'tts-1',
    voice: 'alloy',
    timeout: 60,
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
    save_mode: TTS_CONTRACT_VALUES.saveModeDisabled,
    provider: value?.provider === 'openai-compatible' ? 'openai-compatible' : TTS_PROVIDER,
    base_url: stringValue(value?.base_url, defaults.base_url),
    api_key: stringValue(value?.api_key, defaults.api_key),
    model: stringValue(value?.model, defaults.model),
    voice: stringValue(value?.voice, defaults.voice),
    timeout: Number.isFinite(Number(value?.timeout)) ? Math.max(1, Number(value?.timeout)) : defaults.timeout,
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
  form.tts.base_url = profile.base_url
  form.tts.api_key = profile.api_key
  form.tts.model = profile.model
  form.tts.voice = profile.voice
  form.tts.timeout = profile.timeout
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
  base_url: profile.base_url,
  api_key: profile.api_key,
  model: profile.model,
  voice: profile.voice,
  timeout: profile.timeout,
})

const saveActiveTtsPatch = (patch: SettingsPatch) => {
  const activeProfile = snapshotTtsProfile()
  const runtimePatch: SettingsPatch = { ...ttsRuntimePatchFromProfile(activeProfile), ...patch, save_mode: TTS_CONTRACT_VALUES.saveModeDisabled }
  if (!Object.prototype.hasOwnProperty.call(patch, 'api_key') || activeProfile.provider !== 'openai-compatible') delete runtimePatch.api_key
  debouncedSave({ tts: runtimePatch })
}

const selectedGenieCharacter = computed(() => genieCharacters.value.find((item) => item.id === form.tts.genie_character) || null)

const genieCharacterOptionLabel = (character: GenieCharacterResource): string => (
  character.ready ? character.label : `${character.label} · ${t('settings.tts.resourceIncomplete')}`
)

const loadGenieCharacters = async () => {
  const result = await genieCharactersRequest.execute(() => settingsClient.ttsCharacters())
  if (result) genieCharacters.value = result.characters
}

const selectGenieCharacter = (value: unknown) => {
  const selected = genieCharacters.value.find((item) => item.id === String(value || ''))
  if (!selected) {
    saveTtsField('genie_character', value)
    return
  }
  form.tts.genie_character = selected.id
  form.tts.genie_model_dir = selected.model_dir
  form.tts.ref_audio = selected.ref_audio
  form.tts.ref_text = selected.ref_text
  saveActiveTtsPatch({
    genie_character: selected.id,
    genie_model_dir: selected.model_dir,
    ref_audio: selected.ref_audio,
    ref_text: selected.ref_text,
  })
  void flushPendingSave()
}

const setTtsFormField = (field: TtsProfileField, value: unknown) => {
  if (field === 'provider') {
    form.tts.provider = value === 'openai-compatible' ? 'openai-compatible' : 'genie-tts'
    return
  }
  if (field === 'device') {
    form.tts.device = value === 'cuda' ? 'cuda' : 'cpu'
    return
  }
  if (field === 'save_mode') {
    form.tts.save_mode = TTS_CONTRACT_VALUES.saveModeDisabled
    return
  }
  if (field === 'timeout') {
    form.tts.timeout = Number(value)
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
  const hasStoredKey = provider === llmProviderPreset.value && llmApiKeyStored.value
  if (llmProfileNeedsApiKey(profile) && !profile.api_key.trim() && !hasStoredKey) {
    return { status: t('settings.providerStatus.missingKey'), statusClass: 'warning' }
  }
  if (!profile.model.trim()) {
    return { status: t('settings.providerStatus.modelMissing'), statusClass: 'warning' }
  }
  return { status: t('settings.providerStatus.ready'), statusClass: 'ready' }
}

const ttsProfileHasRunnableConfig = (profile: TtsProfile): boolean => {
  if (profile.provider === 'openai-compatible') return Boolean(profile.base_url.trim() && profile.model.trim() && profile.voice.trim())
  return Boolean(profile.genie_character.trim() || (profile.ref_audio.trim() && profile.ref_text.trim()))
}

const llmProviderOptionRows = computed(() => llmProviderOptions.value.map((option) => ({
  ...option,
  ...getLlmProviderStatus(option.value),
})))

const hasLlmEndpoint = computed(() => Boolean(form.llm.base_url.trim() && form.llm.model.trim()))
const hasLlmApiKey = computed(() => !llmProviderNeedsApiKey.value || Boolean(form.llm.api_key.trim()) || llmApiKeyStored.value)
const canRequestLlmModels = computed(() => Boolean(normalizeOpenAiBaseUrl(form.llm.base_url) && hasLlmApiKey.value))
const hasTtsVoice = computed(() => {
  return ttsProfileHasRunnableConfig(sanitizeTtsProfile(form.tts))
})
const llmModelSelectOptions = computed(() => {
  const current = form.llm.model.trim()
  const options = [...llmModels.value]
  if (current && !options.includes(current)) {
    options.unshift(current)
  }
  return options
})

const llmRuntimeLabel = computed(() => {
  if (serviceApplicationHint('llm')) return serviceApplicationHint('llm')
  if (llmStatusRequest.loading) return t('settings.llm.runtime.reading')
  if (llmStatusRequest.error) return t('settings.llm.runtime.failed')
  const snapshot = llmStatus.value
  if (!snapshot) return t('settings.llm.runtime.unread')
  if (snapshot.preconnect_running) return t('settings.llm.runtime.checking')
  if (snapshot.available && snapshot.last_preconnect_ok !== false) return t('settings.llm.runtime.ready')
  return t('settings.llm.runtime.offline')
})

const llmRuntimeTagType = computed<TagType>(() => {
  const applicationTag = serviceApplicationTag('llm')
  if (applicationTag) return applicationTag
  if (llmStatusRequest.error || (llmStatus.value && !llmStatus.value.available)) return 'danger'
  if (llmStatusRequest.loading || llmStatus.value?.preconnect_running) return 'warning'
  if (llmStatus.value?.available && llmStatus.value.last_preconnect_ok !== false) return 'success'
  return 'info'
})

const llmModelStatusLabel = computed(() => {
  if (llmModelsRequest.loading) return t('settings.llm.modelsReading')
  if (llmModelsRequest.error) return llmModelsRequest.error
  return llmModelStatus.value
})

const canAutoDiscoverLlmModels = computed(() => {
  return shouldAutoDiscoverLlmModels(
    form.llm.base_url,
    llmProviderNeedsApiKey.value ? (form.llm.api_key || (llmApiKeyStored.value ? SETTINGS_SECRET_MASK : '')) : '',
  )
})

const saveError = computed(() => [...saveQueue.failureScopes.value.values()].reverse()
  .find(failure => failure.owner === saveOwner)?.error || updateRequest.error)
const saveSending = computed(() => updateRequest.loading || saveInFlight.value)
const saveBusy = computed(() => saveSending.value || Boolean(pendingSavePatch.value))

const saveStatusType = computed<AlertType>(() => {
  if (saveBusy.value) return 'warning'
  if (failedSavePatch.value) return 'error'
  if (saveError.value) return 'error'
  if (runtimeFailedSections.value.length || runtimeStatusRequest.error) return 'error'
  if (lastRuntimePending.value.length) return 'warning'
  if (lastSavedAt.value) return 'success'
  return 'info'
})

const saveStatusLabel = computed(() => {
  if (saveSending.value) return t('settings.status.saving')
  if (pendingSavePatch.value) return t('settings.status.pending')
  if (settingsReadbackFailed.value) return t('settings.status.readbackFailed')
  if (failedSavePatch.value) return t('settings.status.saveFailed')
  if (saveError.value) return t('settings.status.saveFailed')
  if (lastSavedAt.value) return t('settings.status.saved')
  return ''
})

const saveStatusDetail = computed(() => {
  if (saveSending.value) return t(pendingSavePatch.value ? 'settings.status.savingQueued' : 'settings.status.savingShort')
  if (pendingSavePatch.value) return t('settings.status.pendingDetail')
  if (settingsReadbackFailed.value) return t('settings.messages.readbackFailed')
  if (failedSavePatch.value) return t('settings.status.retrySaveDetail')
  if (saveError.value) return saveError.value
  if (runtimeStatusRequest.error) return t('settings.status.runtimeUnknown')
  if (runtimeFailedSections.value.length) return t('settings.status.runtimeFailed', { items: runtimeFailedSections.value.join(' / ') })
  if (lastRuntimePending.value.length) return t('settings.status.runtimePending', { items: lastRuntimePending.value.join(' / ') })
  if (lastApplied.value.length) return t('settings.status.serviceApplied', { items: lastApplied.value.join(' / ') })
  if (lastSavedAt.value) return t('settings.status.recent', { time: lastSavedAt.value })
  return ''
})

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
  requiredOnFirstRun: boolean
  license: string
  downloadBytes: number
  resumable: ResumableResourceDownload | null
}
const resourceDownloadOptions = computed<ResourceDownloadOption[]>(() => {
  const status = resourceView.value
  if (!status) return []
  const options: Array<Omit<ResourceDownloadOption, 'resumable'>> = [
    { ...status.sherpaOnline.metadata, id: 'sherpa_online', label: t('settingsPanel.resourceSherpaOnline'), ready: status.sherpaOnline.ready },
    { ...status.sherpa.metadata, id: 'sherpa', label: t('settingsPanel.resourceSherpa'), ready: status.sherpa.ready },
    { ...status.tts.metadata, id: 'tts', label: 'Genie TTS', ready: status.tts.ready },
    { ...status.embedding.metadata, id: 'embedding', label: t('settingsPanel.resourceEmbedding'), ready: status.embedding.ready },
    { ...status.soulx.metadata, id: 'soulx', label: t('settingsPanel.resourceSoulx'), ready: status.soulx.ready },
  ]
  return options.map((item) => ({
    ...item,
    resumable: status.resumableDownloads.find((download) => download.resourceId === item.id) ?? null,
  }))
})

const selectRequiredResources = (status: ModelResourceStatusPayload | null): void => {
  if (!status || selectedResourceIds.value.length > 0) return
  const options = [
    { id: 'sherpa_online' as const, status: status.sherpaOnline },
    { id: 'sherpa' as const, status: status.sherpa },
    { id: 'tts' as const, status: status.tts },
    { id: 'embedding' as const, status: status.embedding },
  ]
  selectedResourceIds.value = options
    .filter((item) => item.status.metadata.requiredOnFirstRun && !item.status.ready)
    .map((item) => item.id)
}

const formatStorageBytes = (value: number): string => {
  const bytes = Math.max(0, Number(value) || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GiB`
}

const formatResourceDownloadBytes = (value: number): string => value > 0 ? formatStorageBytes(value) : t('settingsPanel.resourcePerModel')

const storageCategoryLabel = (id: StorageCategoryId): string => t(`settings.storage.category.${id}`)

const notifySaveIdle = () => {
  if (saveInFlight.value || pendingSavePatch.value) return
  const resolvers = saveQueue.idleResolvers
  saveQueue.idleResolvers = []
  resolvers.forEach((resolve) => resolve(true))
}

const waitForSaveIdle = async () => {
  if (!saveInFlight.value && !pendingSavePatch.value) return
  await new Promise<boolean>((resolve) => saveQueue.idleResolvers.push(resolve))
}

const promoteFailedSavePatch = () => {
  if (!failedSavePatch.value) return
  pendingSavePatch.value = pendingSavePatch.value
    ? mergePatch(failedSavePatch.value, pendingSavePatch.value)
    : failedSavePatch.value
  saveQueue.pendingFields = new Map([...saveQueue.failedFields, ...saveQueue.pendingFields])
  saveQueue.failedFields.clear()
  failedSavePatch.value = null
}

const queueSavePatch = (patch: SettingsPatch) => {
  patch = stripDeletingSensitiveKeys(patch) || {}
  if (!Object.keys(patch).length) return
  promoteFailedSavePatch()
  pendingSavePatch.value = stripDeletingSensitiveKeys(pendingSavePatch.value)
  pendingSavePatch.value = pendingSavePatch.value
    ? mergePatch(pendingSavePatch.value, patch)
    : patch
  for (const [path] of settingsPatchFields(patch)) {
    const token = Symbol('settings-field')
    saveQueue.pendingFields.set(path, token)
    draftReceipts.set(path, { token, value: JSON.stringify(draftFieldValue(path)) })
    laterDraftFields.delete(path)
  }
}

const captureFormDraft = () => snapshotSettingsDraft({ form, profiles: llmProfiles, provider: llmProviderPreset.value })
const initialDraft = captureFormDraft()
let hydratedDraft: ReturnType<typeof captureFormDraft> | null = null
let reconcilingDraft = false
const draftReceipts = new Map<string, { token: symbol; value: string | undefined }>()
const laterDraftFields = new Set<string>()
const draftFieldValue = (path: string): unknown => {
  const parts = JSON.parse(path) as string[]
  let value: unknown = form
  if (parts[0] === 'llm' && parts[1] === 'profiles') {
    value = llmProfiles
    parts.splice(0, 2)
  }
  for (const part of parts) value = isPlainRecord(value) ? value[part] : undefined
  return value
}

// Invalidate receipts synchronously: editing away and back still creates a new draft.
watch([form, llmProfiles], () => {
  if (reconcilingDraft) return
  for (const [path, receipt] of draftReceipts) {
    if (JSON.stringify(draftFieldValue(path)) === receipt.value) continue
    draftReceipts.delete(path)
    laterDraftFields.add(path)
  }
}, { deep: true, flush: 'sync' })

const acknowledgedSubmission = (patch: SettingsPatch, fields: SettingsFieldTokens): SettingsPatch =>
  selectSettingsFields(patch, (path) => {
    const receipt = draftReceipts.get(path)
    return Boolean(receipt && receipt.token === fields.get(path))
  })

const finishSubmission = (fields: SettingsFieldTokens, recoveries: Set<symbol>) => {
  for (const [path, token] of fields) {
    if (draftReceipts.get(path)?.token === token) draftReceipts.delete(path)
  }
  if (saveErrorId && recoveries.has(saveErrorId)) {
    updateRequest.reset()
    saveErrorId = null
  }
}

// A queued patch may have been superseded by local typing before it is sent.
// Only fields still equal to that submitted value acknowledge this view's draft.
const acknowledgedDraftFields = (draft: SettingsPatch, submitted: SettingsPatch): SettingsPatch => {
  const acknowledged: SettingsPatch = {}
  for (const [key, value] of Object.entries(submitted)) {
    if (isPlainRecord(value) && isPlainRecord(draft[key])) {
      const nested = acknowledgedDraftFields(draft[key], value)
      if (Object.keys(nested).length) acknowledged[key] = nested
    } else if (JSON.stringify(draft[key]) === JSON.stringify(value)) acknowledged[key] = value
  }
  return acknowledged
}

const hydratePreservingDraft = (before: ReturnType<typeof captureFormDraft>, source = settings.value, submitted: SettingsPatch = {}, explicitMutation = false) => {
  if (!source || unmounted) return
  reconcilingDraft = true
  try {
    const current = captureFormDraft()
    const hydratedBefore = hydratedDraft
    const sharedDraft = mergePatch(saveQueue.active.value || {}, mergePatch(failedSavePatch.value || {}, pendingSavePatch.value || {}))
    if (!hydratedBefore) {
      // Seed a new view with the shared draft, then preserve input typed during its GET.
      // Later acknowledgements must still normalize these inherited values.
      hydrateForm(mergePatch(source as unknown as SettingsPatch, sharedDraft) as unknown as SettingsResponse)
      hydratedDraft = captureFormDraft()
      for (const [path] of settingsPatchFields(sharedDraft)) {
        const token = saveQueue.pendingFields.get(path) || saveQueue.failedFields.get(path) || saveQueue.activeFields.get(path)
        if (token) draftReceipts.set(path, { token, value: JSON.stringify(draftFieldValue(path)) })
      }
      restoreLaterSettingsDraft(form, initialDraft.form, current.form)
      restoreLaterSettingsDraft(llmProfiles, initialDraft.profiles, current.profiles)
      if (before.provider !== current.provider) llmProviderPreset.value = current.provider
      return
    }
    const submittedDraft = { ...before.form, llm: { ...before.form.llm, profiles: before.profiles } }
    const acknowledged = explicitMutation ? submitted : acknowledgedDraftFields(submittedDraft, submitted)
    const unsent = unsentSettingsDraft(hydratedBefore.form, before.form, acknowledged)
    hydrateForm(source)
    hydratedDraft = captureFormDraft()
    if (explicitMutation) {
      for (const [path] of settingsPatchFields(submitted)) {
        laterDraftFields.delete(path)
        draftReceipts.delete(path)
      }
    }
    const currentFields = { ...current.form, llm: { ...current.form.llm, profiles: current.profiles } }
    const later = selectSettingsFields(currentFields, (path) => laterDraftFields.has(path))
    const queued = mergePatch(mergePatch(unsent, sharedDraft), later)
    restoreLaterSettingsDraft(form, before.form, current.form, queued)
    const unsentProfiles = hydratedBefore ? unsentSettingsDraft(hydratedBefore.profiles, before.profiles, isPlainRecord(acknowledged.llm) && isPlainRecord(acknowledged.llm.profiles) ? acknowledged.llm.profiles : {}) : {}
    const queuedProfiles = isPlainRecord(queued.llm) && isPlainRecord(queued.llm.profiles) ? queued.llm.profiles : {}
    restoreLaterSettingsDraft(llmProfiles, before.profiles, current.profiles, mergePatch(unsentProfiles, queuedProfiles))
    if (before.provider !== current.provider || (hydratedBefore && hydratedBefore.provider !== before.provider && !(isPlainRecord(submitted.llm) && 'provider' in submitted.llm)) || (isPlainRecord(queued.llm) && 'provider' in queued.llm)) {
      llmProviderPreset.value = current.provider
    }
  } finally {
    reconcilingDraft = false
  }
}

const recordSettingsSaved = (result: Pick<SettingsMutationResponse, 'runtime_applied' | 'runtime_changed' | 'runtime_reload'>) => {
  const applied = result.runtime_applied || []
  lastSavedAt.value = new Date().toLocaleTimeString(undefined, { hour12: false })
  if (result.runtime_reload) {
    acceptRuntimeStatus(result.runtime_reload)
    syncRuntimeReloadDisplay()
  } else {
    // Older backends acknowledge config only; service application is unknown.
    lastApplied.value = []
    lastRuntimePending.value = result.runtime_changed || []
  }
  scheduleRuntimeStatusPoll()
  if (!result.runtime_reload && applied.includes('tts') && isSectionVisible('voice')) void loadTtsStatus()
}

const savePatch = async (patch: SettingsPatch, fields: SettingsFieldTokens) => {
  const before = captureFormDraft()
  const result = await patchSettings(patch)
  settingsReadbackFailed.value = localSettingsReadbackFailed.value
  if (result) {
    const normalized = result.normalizedSettings
    for (const [section, values] of Object.entries(normalized)) {
      const target = settingsStore.state[section as keyof typeof settingsStore.state]
      if (target && typeof target === 'object' && values && typeof values === 'object') {
        Object.assign(target, values)
      }
    }
    const recoveries = acknowledgeSettingsFailures(settingsPatchFields(patch).map(([path]) => path))
    saveQueue.active.value = null
    saveQueue.completion.value = { ...result, submitted: patch, owner: saveOwner, fields, recoveredFailures: recoveries }
    if (!unmounted) {
      hydratePreservingDraft(before, normalized, acknowledgedSubmission(patch, fields))
      recordSettingsSaved(result)
      void prepareResourcesForSettingsPatch(patch)
    }
    finishSubmission(fields, recoveries)
  } else {
    saveErrorId = Symbol('settings-save-failure')
    saveQueue.failureScopes.value = new Map([...saveQueue.failureScopes.value, [saveErrorId, { owner: saveOwner, fields: new Set(settingsPatchFields(patch).map(([path]) => path)), error: updateRequest.error || t('settings.messages.saveFailed') }]])
    ElMessage.error(t(settingsReadbackFailed.value ? 'settings.messages.readbackFailed' : 'settings.messages.saveFailed'))
  }
  return result
}

const parkFailedSavePatch = (patch: SettingsPatch | null, fields: SettingsFieldTokens) => {
  if (!patch) return
  const queuedAfterFailure = pendingSavePatch.value
  pendingSavePatch.value = null
  failedSavePatch.value = queuedAfterFailure
    ? mergePatch(patch, queuedAfterFailure)
    : patch
  saveQueue.failedFields = new Map([...fields, ...saveQueue.pendingFields])
  saveQueue.pendingFields = new Map()
}

const drainSaveQueue = async () => {
  if (saveInFlight.value || saveQueue.adminInFlight) return
  if (saveQueue.timeout) clearTimeout(saveQueue.timeout)
  saveQueue.timeout = null
  saveQueue.queuedAt = null
  if (!pendingSavePatch.value) return
  saveInFlight.value = true
  let activePatch: SettingsPatch | null = null
  let activeFields: SettingsFieldTokens = new Map()
  try {
    while (pendingSavePatch.value) {
      activePatch = pendingSavePatch.value
      const paths = new Set(settingsPatchFields(activePatch).map(([path]) => path))
      activeFields = new Map([...saveQueue.pendingFields].filter(([path]) => paths.has(path)))
      saveQueue.pendingFields = new Map()
      saveQueue.active.value = activePatch
      saveQueue.activeFields = activeFields
      pendingSavePatch.value = null
      const result = await savePatch(activePatch, activeFields)
      if (!result) {
        saveQueue.failures += 1
        parkFailedSavePatch(activePatch, activeFields)
        break
      }
      activePatch = null
    }
  } catch (error) {
    console.error('[Settings Save Queue]:', error)
    saveQueue.failures += 1
    parkFailedSavePatch(activePatch, activeFields)
    ElMessage.error(t('settings.messages.saveFailed'))
  } finally {
    saveInFlight.value = false
    saveQueue.active.value = null
    saveQueue.activeFields = new Map()
    notifySaveIdle()
  }
}

const debouncedSave = (patch: SettingsPatch) => {
  if (unmounted) return
  if (saveQueue.timeout) clearTimeout(saveQueue.timeout)
  saveQueue.timeout = null
  queueSavePatch(patch)
  if (!pendingSavePatch.value || saveInFlight.value) return
  saveQueue.queuedAt ??= Date.now()
  const delay = Math.min(SAVE_DEBOUNCE_MS, Math.max(0, SAVE_MAX_WAIT_MS - (Date.now() - saveQueue.queuedAt)))
  saveQueue.timeout = setTimeout(() => {
    saveQueue.timeout = null
    void drainSaveQueue()
  }, delay)
}

const retryFailedSave = () => {
  if (!failedSavePatch.value || saveBusy.value) return
  promoteFailedSavePatch()
  void drainSaveQueue()
}

const applyLlmVisionPatch = (patch: LlmVisionPatch) => {
  const settingsPatch: Record<string, unknown> = {}
  if (patch.enabled !== undefined) {
    form.llm.vision_enabled = patch.enabled
    settingsPatch.vision_enabled = patch.enabled
  }
  if (patch.provider !== undefined) {
    form.llm.vision_provider = patch.provider
    settingsPatch.vision_provider = patch.provider
  }
  if (patch.baseUrl !== undefined) {
    form.llm.vision_base_url = patch.baseUrl
    settingsPatch.vision_base_url = patch.baseUrl
  }
  if (patch.apiKey !== undefined) {
    form.llm.vision_api_key = patch.apiKey
    settingsPatch.vision_api_key = patch.apiKey
  }
  if (patch.model !== undefined) {
    form.llm.vision_model = patch.model
    settingsPatch.vision_model = patch.model
  }
  if (patch.timeout !== undefined) {
    form.llm.vision_timeout = patch.timeout
    settingsPatch.vision_timeout = patch.timeout
  }
  if (patch.detail !== undefined) {
    form.llm.vision_detail = patch.detail
    settingsPatch.vision_detail = patch.detail
  }
  if (Object.keys(settingsPatch).length) debouncedSave({ llm: settingsPatch })
}

const flushPendingSave = async () => {
  if (saveQueue.adminInFlight) await new Promise<void>((resolve) => saveQueue.adminResolvers.push(resolve))
  const failureCountBeforeFlush = saveQueue.failures
  if (saveQueue.timeout) {
    clearTimeout(saveQueue.timeout)
    saveQueue.timeout = null
  }
  promoteFailedSavePatch()
  void drainSaveQueue()
  await waitForSaveIdle()
  return saveQueue.failures === failureCountBeforeFlush && !failedSavePatch.value
}

const beginSettingsMutation = async () => {
  for (;;) {
    if (!(await flushPendingSave()) || unmounted) return false
    // Another waiter may have acquired the mutation slot during the flush.
    if (saveQueue.adminInFlight || saveInFlight.value || pendingSavePatch.value) continue
    saveQueue.adminInFlight = true
    return true
  }
}

const finishSettingsMutation = () => {
  saveQueue.adminInFlight = false
  const resolvers = saveQueue.adminResolvers
  saveQueue.adminResolvers = []
  resolvers.forEach((resolve) => resolve())
  if (pendingSavePatch.value) void drainSaveQueue()
}

const setMemoryBackend = (backend: string) => {
  if (form.memory.backend === backend) return
  form.memory.backend = backend
  debouncedSave({ memory: { backend } })
}

const handleMemoryBackendChange = (value: string | number | boolean) => {
  setMemoryBackend(String(value))
}

const refreshMemoryIndexStatus = async () => {
  const sequence = ++memoryIndexStatusSequence
  memoryIndexStatusLoading.value = true
  memoryIndexStatusError.value = ''
  try {
    const status = await memoryClient.getIndexStatus()
    if (unmounted || sequence !== memoryIndexStatusSequence) return
    memoryIndexStatus.value = status
    if (status.job && !memoryRebuildJob.value) {
      memoryRebuildPollStartedAt = Date.now()
      applyMemoryRebuildJob(status.job, false)
    }
  } catch (error) {
    if (!unmounted && sequence === memoryIndexStatusSequence) {
      memoryIndexStatusError.value = describeFailure(error, t('settings.memory.statusFailed'))
    }
  } finally {
    if (sequence === memoryIndexStatusSequence) memoryIndexStatusLoading.value = false
  }
}

const waitForMemoryBackend = async (expectedBackend: string) => {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (unmounted || form.memory.backend !== expectedBackend) return false
    const status = await memoryClient.getIndexStatus()
    if (unmounted || form.memory.backend !== expectedBackend) return false
    memoryIndexStatus.value = status
    if (status.backend === expectedBackend) return true
    await new Promise<void>((resolve) => window.setTimeout(resolve, 100))
  }
  return false
}

const stopMemoryRebuildPolling = () => {
  if (memoryRebuildPollTimer !== null) window.clearTimeout(memoryRebuildPollTimer)
  memoryRebuildPollTimer = null
}

const applyMemoryRebuildJob = (job: MemoryIndexRebuildJob, notifyCompletion = true) => {
  const previous = memoryRebuildJob.value
  memoryRebuildJob.value = job
  memoryRebuildError.value = ''
  stopMemoryRebuildPolling()
  if (job.state === 'completed') {
    if (notifyCompletion && (previous?.job_id !== job.job_id || previous.state !== 'completed')) {
      ElMessage.success(t('settings.messages.memoryRebuildOk', {
        count: Number(job.result?.indexed_count ?? job.processed_count ?? 0),
        skipped: Number(job.result?.skipped_count ?? 0),
      }))
    }
  } else if (['failed', 'interrupted'].includes(job.state)) {
    memoryRebuildError.value = job.last_error || t('settings.messages.memoryRebuildFailed')
  } else if (!['cancelled'].includes(job.state) && isSectionVisible('memory')) {
    if (Date.now() - memoryRebuildPollStartedAt >= 10 * 60 * 1000) {
      memoryRebuildError.value = t('settings.memory.rebuildPollStopped')
    } else {
      memoryRebuildPollTimer = window.setTimeout(() => void refreshMemoryRebuild(), 1500)
    }
  }
}

const refreshMemoryRebuild = async () => {
  const jobId = memoryRebuildJob.value?.job_id
  if (!jobId || memoryRebuildRefreshing.value || memoryRebuildCancelling.value || unmounted) return
  stopMemoryRebuildPolling()
  memoryRebuildRefreshing.value = true
  try {
    const result = await memoryClient.getIndexRebuildJob(jobId)
    if (!unmounted && memoryRebuildJob.value?.job_id === jobId) applyMemoryRebuildJob(result.job)
  } catch (error) {
    if (!unmounted) memoryRebuildError.value = describeFailure(error, t('settings.messages.memoryRebuildFailed'))
  } finally {
    memoryRebuildRefreshing.value = false
  }
}

const cancelMemoryRebuild = async () => {
  const jobId = memoryRebuildJob.value?.job_id
  if (!jobId || !memoryIndexWorking.value || memoryRebuildRefreshing.value || memoryRebuildCancelling.value || unmounted) return
  stopMemoryRebuildPolling()
  memoryRebuildCancelling.value = true
  try {
    const result = await memoryClient.cancelIndexRebuild(jobId)
    if (!unmounted && memoryRebuildJob.value?.job_id === jobId) applyMemoryRebuildJob(result.job)
  } catch (error) {
    if (!unmounted) memoryRebuildError.value = describeFailure(error, t('settings.messages.memoryRebuildFailed'))
  } finally {
    memoryRebuildCancelling.value = false
  }
}

const handleRebuildMemoryIndex = async () => {
  if (memoryIndexWorking.value) return
  if (form.memory.backend === 'inmemory') {
    ElMessage.warning(t('settingsPanel.message.inMemoryNoIndex'))
    return
  }
  memoryRebuildStarting.value = true
  memoryRebuildError.value = ''
  try {
    if (!(await flushPendingSave()) || unmounted) return
    const backend = form.memory.backend
    if (!(await waitForMemoryBackend(backend))) {
      memoryRebuildError.value = t('settingsPanel.message.memoryBackendSwitching')
      return
    }
    const result = await memoryRebuildRequest.execute(() => memoryClient.rebuildIndex())
    if (unmounted) return
    if (!result) {
      memoryRebuildError.value = memoryRebuildRequest.error || t('settings.messages.memoryRebuildFailed')
      return
    }
    memoryRebuildPollStartedAt = Date.now()
    applyMemoryRebuildJob(result.job)
  } catch (error) {
    if (!unmounted) memoryRebuildError.value = describeFailure(error, t('settings.messages.memoryRebuildFailed'))
  } finally {
    memoryRebuildStarting.value = false
  }
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
    ElMessage.error(describeFailure(error, t('settingsPanel.message.desktopShortcutSaveFailed')))
  }
}

const setPushToTalkEnabled = (value: string | number | boolean) => {
  void updateDesktopInputBindings({ pushToTalk: { enabled: Boolean(value) } })
}

const setBrowserShortcutsEnabled = (value: string | number | boolean) => {
  inputBindingsStore.setBrowserShortcutsEnabled(Boolean(value))
}

const setPushToTalkMouseButton = (value: unknown) => {
  const mouseButton: MouseSideButton = Number(value) === 4 ? 4 : 5
  void updateDesktopInputBindings({ pushToTalk: { mouseButton } })
}

const captureKeyboardBinding = (action: KeyboardShortcutAction, event: KeyboardEvent) => {
  if (event.key === 'Escape') return
  const accelerator = keyboardEventToAccelerator(event, Boolean(inputBindingState.browserFallback))
  if (!accelerator) {
    ElMessage.warning(t('settingsPanel.message.shortcutNeedsModifier'))
    return
  }
  void setKeyboardBinding(action, accelerator)
}

const clearKeyboardBinding = (action: KeyboardShortcutAction) => {
  void updateDesktopInputBindings({ keyboard: { [action]: '' } })
}

const setKeyboardBinding = async (action: KeyboardShortcutAction, value: string) => {
  const accelerator = normalizeKeyboardAccelerator(value)
  if (value.trim() && !accelerator) {
    ElMessage.warning(t('settingsPanel.message.shortcutInvalid'))
    return
  }
  if (!inputBindingState.browserFallback && accelerator && !accelerator.includes('+') && !accelerator.startsWith('F')) {
    ElMessage.warning(t('settingsPanel.message.shortcutNeedsModifierOrFunctionKey'))
    return
  }
  const keyboard = { ...inputBindingState.settings.keyboard, [action]: accelerator }
  const conflicts = findKeyboardBindingConflicts(keyboard)
  if (conflicts.length) {
    ElMessage.warning(t('settingsPanel.message.shortcutDuplicate', { actions: conflicts[0].actions.join('、') }))
    return
  }
  await updateDesktopInputBindings({ keyboard: { [action]: accelerator } })
}

const retryDesktopInputBindings = () => {
  void inputBindingsStore.load()
}

const resetDesktopInputBindings = async () => {
  try {
    await inputBindingsStore.reset()
    ElMessage.success(t('settingsPanel.message.desktopInputReset'))
  } catch (error) {
    ElMessage.error(describeFailure(error, t('settingsPanel.message.desktopInputResetFailed')))
  }
}

const discoverLocalRuntime = async (): Promise<LocalRuntimeDiscoveryResponse | null> => {
  if (!(await flushPendingSave()) || unmounted || localDiscoveryRequest.loading) return null
  const before = JSON.stringify(captureFormDraft())
  const result = await localDiscoveryRequest.execute(() => settingsClient.discoverLocal())
  if (unmounted) return null
  if (result && before !== JSON.stringify(captureFormDraft())) {
    ElMessage.info(t('settings.messages.discoveryDraftChanged'))
    return null
  }
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
  ElMessage.info(t('settings.messages.localDetectDraft', { service: candidate.label || candidate.provider || candidate.backend || fallback }))
}


const applyLocalAsrDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  if (!discovery) return
  const candidate = firstReadyCandidate(discovery.asr)
  if (!candidate?.base_url) {
    warnNoLocalCandidate('ASR')
    return
  }
  const provider = String(candidate.provider || 'sherpa-onnx')
  form.asr.provider = provider
  form.asr.base_url = candidate.base_url
  debouncedSave({ asr: { provider, base_url: candidate.base_url } })
  notifyLocalCandidateApplied(candidate, 'ASR')
}

const applyLocalTtsDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  if (!discovery) return
  const candidate = firstReadyCandidate(discovery.tts)
  if (!candidate) {
    warnNoLocalCandidate('Genie TTS')
    return
  }
  form.tts.provider = TTS_PROVIDER
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

const saveSvcField = (field: keyof SvcSettings, value: string | number) => {
  form.svc[field] = value as never
  svcTestResult.value = null
  debouncedSave({ svc: { [field]: value } })
}

const resetSvcSettings = () => {
  const defaults: SvcSettings = {
    provider: 'soulx-service',
    base_url: '',
    speaker_id: 0,
    pitch: 0,
    timeout: 120,
  }
  Object.assign(form.svc, defaults)
  svcTestResult.value = null
  debouncedSave({ svc: defaults })
}

const openServiceSettings = async (section: 'llm' | 'voice' | 'asr') => {
  if (!(await flushPendingSave()) || unmounted) return
  activeSection.value = section
}

const applyLocalSvcDiscovery = async () => {
  const discovery = await discoverLocalRuntime()
  if (!discovery) return
  const candidate = firstReadyCandidate(discovery.svc)
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
  if (!discovery) return
  const candidate = firstReadyCandidate(discovery.memory)
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

const llmModelDiscoveryKey = (): string => JSON.stringify([
  llmProviderPreset.value,
  normalizeOpenAiBaseUrl(form.llm.base_url),
  llmProviderNeedsApiKey.value ? (form.llm.api_key.trim() || (llmApiKeyStored.value ? SETTINGS_SECRET_MASK : '')) : '',
  form.llm.timeout,
])

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

const refreshBackendTokenStatus = async () => {
  const result = await backendTokenStatusRequest.execute(() => settingsClient.backendTokenStatus())
  if (result) {
    backendTokenStatus.value = result
  }
  return result
}

const saveBackendToken = async () => {
  const token = backendTokenInput.value.trim()
  if (backendTokenMutationRequest.loading) return
  if (!token) {
    ElMessage.warning(t('settings.messages.backendTokenRequired'))
    return
  }

  const result = await backendTokenMutationRequest.execute(() => settingsClient.setBackendToken(token))
  if (!result?.ok) {
    ElMessage.error(backendTokenMutationRequest.error || t('common.error.unknown'))
    return
  }

  if (backendTokenInput.value.trim() === token) backendTokenInput.value = ''
  const status = await refreshBackendTokenStatus()
  if (!status) {
    ElMessage.warning(t('settings.messages.readbackFailed'))
    return
  }
  ElMessage.success(result.requiresRestart ? t('settings.messages.backendTokenSavedRestart') : t('settings.messages.backendTokenSaved'))
}

const resetBackendToken = async () => {
  if (backendTokenMutationRequest.loading) return
  const inputBefore = backendTokenInput.value
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

  if (backendTokenMutationRequest.loading) return
  const result = await backendTokenMutationRequest.execute(() => settingsClient.resetBackendToken())
  if (!result?.ok) {
    ElMessage.error(backendTokenMutationRequest.error || t('common.error.unknown'))
    return
  }

  if (backendTokenInput.value === inputBefore) backendTokenInput.value = ''
  const status = await refreshBackendTokenStatus()
  if (!status) {
    ElMessage.warning(t('settings.messages.readbackFailed'))
    return
  }
  ElMessage.success(result.requiresRestart ? t('settings.messages.backendTokenResetRestart') : t('settings.messages.backendTokenReset'))
}

const handleTestLlm = async () => {
  if (!(await flushPendingSave()) || unmounted) return
  const tested = JSON.stringify(form.llm)
  const res = await testLlm()
  if (unmounted || tested !== JSON.stringify(form.llm)) return
  if (res?.ready ?? res?.ok ?? res?.status === 'ok') {
    ElMessage.success(t('settings.messages.llmOk'))
  } else if (res) {
    ElMessage.error(t('settings.messages.llmFailed', { message: res.message || t('common.error.unknown') }))
  } else {
    ElMessage.error(testLlmRequest.error || t('common.error.unknown'))
  }
}

const refreshLlmStatus = async () => {
  await loadLlmStatus()
}

const refreshTtsStatus = async (): Promise<TtsRuntimeStatusResponse | null> => {
  return loadTtsStatus()
}

const queueTtsWarmup = async () => {
  if (!isSectionVisible('voice')) return
  if (unmounted || !settings.value || !hasTtsVoice.value || !(await flushPendingSave())) return
  if (!isSectionVisible('voice')) return
  const snapshot = ttsStatus.value
  if (warmupTtsRequest.loading || snapshot?.warmup_done || snapshot?.warmup_running || snapshot?.warming_up) return
  const result = await warmupTts()
  if (!result && !unmounted) ElMessage.error(warmupTtsRequest.error || t('settings.messages.ttsWarmupFailed'))
  if (result?.ok && isSectionVisible('voice')) {
    void loadTtsStatus()
  }
}

const handleWarmupTts = async () => {
  if (!hasTtsVoice.value) {
    ElMessage.warning(t('settings.messages.ttsWarmupNeedsConfig'))
    return
  }
  if (!(await flushPendingSave()) || unmounted) return
  const result = await warmupTts()
  void refreshTtsStatus()
  if (unmounted) return
  if (result?.ok || result?.queued) {
    ElMessage.success(t('settings.messages.ttsWarmupQueued'))
  } else if (result) {
    ElMessage.error(result.message || t('settings.messages.ttsWarmupFailed'))
  } else {
    ElMessage.error(warmupTtsRequest.error || t('settings.messages.ttsWarmupFailed'))
  }
}

const handleTestTts = async () => {
  if (!(await flushPendingSave()) || unmounted) return
  const tested = JSON.stringify(form.tts)
  const res = await testTts()
  void refreshTtsStatus()
  if (unmounted || tested !== JSON.stringify(form.tts)) return
  if (res?.ready ?? res?.ok ?? res?.status === 'ok') {
    ElMessage.success(t('settings.messages.ttsOk'))
  } else if (res) {
    ElMessage.error(t('settings.messages.ttsFailed', { message: res.message || t('settings.messages.ttsHint') }))
  } else {
    ElMessage.error(testTtsRequest.error || t('common.error.unknown'))
  }
}

const handleTestSvc = async () => {
  if (!(await flushPendingSave()) || unmounted) return
  svcTestResult.value = null
  const tested = JSON.stringify(form.svc)
  const res = await testSvc()
  if (unmounted || tested !== JSON.stringify(form.svc)) return
  if (res?.ready ?? res?.ok ?? res?.status === 'ok') {
    svcTestResult.value = { ok: true, message: res.message }
    ElMessage.success(res.message || t('settings.messages.svcOk'))
  } else if (res) {
    svcTestResult.value = { ok: false, message: res.message }
    ElMessage.error(t('settings.messages.svcFailed', { message: res.message || t('common.error.unknown') }))
  } else {
    svcTestResult.value = { ok: false, message: testSvcRequest.error || t('common.error.unknown') }
  }
}

const loadSettingsAdmin = async () => {
  try {
    const [metadata, history] = await Promise.all([settingsClient.metadata(), settingsClient.history()])
    settingsMetadata.value = metadata
    settingsHistory.value = history.history.filter(isPlainRecord)
  } catch (error) {
    settingsMetadata.value = null
    settingsHistory.value = []
    console.info('[Settings] Admin metadata unavailable:', error)
  }
}

const rollbackSettings = async () => {
  if (keyOperation.value) return
  keyOperation.value = 'rollback'
  keyError.value = ''
  const steps = rollbackSteps.value
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.rollbackMessage', { steps: steps }),
      t('settings.confirm.rollbackTitle'),
      {
        confirmButtonText: t('common.rollback'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    finishKeyOperation()
    return
  }

  try {
    keyMutationAcquired = await beginSettingsMutation()
    if (!keyMutationAcquired) {
      keyError.value = t('settings.messages.saveFailed')
      return
    }
    const before = captureFormDraft()
    await settingsClient.rollback(steps)
    await refreshSettingsPreservingDraft(before)
    recordSettingsSaved({})
    await refreshRuntimeApplication()
    ElMessage.success(t('settings.messages.rollbackOk'))
  } catch (error) {
    keyError.value = describeFailure(error, t('common.error.unknown'))
  } finally {
    finishKeyOperation()
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
    ElMessage.error(describeFailure(error, t('common.error.unknown')))
  }
}

const stopResourceProgressPolling = () => {
  if (resourceProgressPollTimer === null) return
  window.clearInterval(resourceProgressPollTimer)
  resourceProgressPollTimer = null
}

const settleResourceCancellation = () => {
  if (!cancellingResourceIds.value.length || resourceStateUncertain) return
  const active = new Set([...activeResourceIds.value, ...activeDownloadProgress.value.map((item) => item.resourceId)])
  if (cancellingResourceIds.value.some((id) => active.has(id))) return
  resourceMessage.value = t('settings.resource.cancelFinished')
  resourceMessageType.value = 'info'
  cancellingResourceIds.value = []
}

const pollResourceStatus = async () => {
  if (resourceProgressPollBusy || !isSectionVisible('resources')) return
  if (Date.now() - resourcePollStartedAt >= 30 * 60 * 1000) {
    stopResourceProgressPolling()
    resourceMessage.value = t('settings.resource.pollStopped')
    resourceMessageType.value = 'warning'
    return
  }
  resourceProgressPollBusy = true
  const version = resourceStatusVersion
  try {
    const hadActiveDownloads = activeDownloadProgress.value.length > 0
    const progress = await resourceClient.progress()
    if (!isSectionVisible('resources') || version !== resourceStatusVersion) return
    if ((hadActiveDownloads || cancellingResourceIds.value.length || resourceStateUncertain) && progress.activeDownloads.length === 0 && !resourceActionKey.value) {
      const status = await resourceClient.status()
      if (unmounted || version !== resourceStatusVersion) return
      resourceStatus.value = normalizeResourceStatus(status)
      resourceStateUncertain = false
    } else if (resourceStatus.value) {
      resourceStatus.value = { ...resourceStatus.value, activeDownloads: progress.activeDownloads }
    }
    resourcePollFailures = 0
    settleResourceCancellation()
  } catch (error) {
    if (unmounted || version !== resourceStatusVersion) return
    resourcePollFailures += 1
    if (resourcePollFailures >= 3) {
      stopResourceProgressPolling()
      resourceMessage.value = describeFailure(error, t('settings.resource.pollStopped'))
      resourceMessageType.value = 'warning'
    }
  } finally {
    resourceProgressPollBusy = false
    if (!resourceActionKey.value && !resourceStateUncertain && !cancellingResourceIds.value.length && activeDownloadProgress.value.length === 0) stopResourceProgressPolling()
  }
}

const syncResourceProgressPolling = () => {
  const shouldPoll = Boolean(resourceActionKey.value) || activeDownloadProgress.value.length > 0 || resourceStateUncertain || cancellingResourceIds.value.length > 0
  if (!shouldPoll || !isSectionVisible('resources')) {
    stopResourceProgressPolling()
    return
  }
  if (resourceProgressPollTimer !== null) return
  resourcePollFailures = 0
  resourcePollStartedAt = Date.now()
  resourceProgressPollTimer = window.setInterval(() => void pollResourceStatus(), RESOURCE_PROGRESS_POLL_INTERVAL_MS)
}

const handleResourceProgressVisibility = () => {
  if (document.hidden || !settingsActive) {
    stopRuntimeStatusPoll()
    stopMemoryRebuildPolling()
    stopResourceProgressPolling()
    invalidateLlmModelDiscovery({ preserveLast: true })
    return
  }
  void refreshActivatedSettings().then(() => {
    void refreshRuntimeApplication()
    return refreshActiveSection()
  })
  scheduleRuntimeStatusPoll()
}

const loadResourceStatus = async () => {
  resourceLoading.value = true
  const version = ++resourceStatusVersion
  try {
    const status = await resourceClient.status()
    if (unmounted || version !== resourceStatusVersion) return
    resourceStatus.value = normalizeResourceStatus(status)
    resourceStateUncertain = false
    settleResourceCancellation()
    selectRequiredResources(resourceStatus.value)
    syncResourceProgressPolling()
  } catch (error) {
    if (unmounted || version !== resourceStatusVersion) return
    const message = describeFailure(error, t('settings.resource.statusFailed'))
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
  if (resourceActionKey.value || activeDownloadProgress.value.length > 0 || resourceStateUncertain || cancellingResourceIds.value.length > 0) {
    ElMessage.warning(t('settingsPanel.message.resourceTaskBusy'))
    return
  }
  resourceStatusVersion += 1
  resourceActionKey.value = key
  activeResourceIds.value = [...resources]
  resourceMessage.value = ''
  syncResourceProgressPolling()
  try {
    const result = await task()
    if (unmounted) return
    resourceStateUncertain = false
    resourceStatusVersion += 1
    resourceStatus.value = normalizeResourceStatus(result.status)
    const incomplete = resources.filter((id) => !resourceDownloadOptions.value.find((item) => item.id === id)?.ready)
    const cancelled = result.errorCode === 'cancelled'
    const complete = result.success && incomplete.length === 0
    const message = !complete && !cancelled && incomplete.length
      ? result.message + ' · ' + t('settings.resource.incomplete', { items: incomplete.join(' / ') })
      : cancelled ? t('settings.resource.cancelled') : result.message
    resourceMessage.value = message
    resourceMessageType.value = complete ? 'success' : cancelled ? 'info' : 'warning'
    if (!complete && !cancelled) selectedResourceIds.value = [...new Set([...selectedResourceIds.value, ...incomplete])]
    if (cancelled) ElMessage.info(message)
    else if (complete) {
      ElMessage.success(message)
    } else {
      ElMessage.warning(message)
    }
  } catch (error) {
    if (unmounted) return
    resourceStateUncertain = true
    const message = describeFailure(error, t('settings.resource.taskFailed'))
    resourceMessage.value = message
    resourceMessageType.value = 'error'
    ElMessage.error(message)
  } finally {
    resourceActionKey.value = ''
    activeResourceIds.value = []
    settleResourceCancellation()
    syncResourceProgressPolling()
  }
}

const cancelActiveResourceDownloads = async () => {
  const resources = [...cancellableResourceIds.value]
  if (resources.length === 0 || resourceCancelLoading.value) return
  resourceCancelLoading.value = true
  const version = ++resourceStatusVersion
  try {
    const result = await resourceClient.cancel(resources)
    if (unmounted) return
    cancellingResourceIds.value = [...new Set([...cancellingResourceIds.value, ...result.cancelled])]
    // A command may already have finished while the cancellation ACK was in flight.
    if (version === resourceStatusVersion) resourceStatus.value = normalizeResourceStatus(result.status)
    resourceStateUncertain = true
    const message = result.cancelled.length > 0
      ? t('settings.resource.cancelPending', { count: result.cancelled.length })
      : t('settingsPanel.message.noCancellableDownloads')
    resourceMessage.value = message
    resourceMessageType.value = result.cancelled.length > 0 ? 'warning' : 'info'
    ElMessage.info(message)
    await loadResourceStatus()
    syncResourceProgressPolling()
  } catch (error) {
    resourceMessage.value = describeFailure(error, t('settings.resource.taskFailed'))
    resourceMessageType.value = 'error'
    ElMessage.error(resourceMessage.value)
  } finally {
    resourceCancelLoading.value = false
  }
}

const prepareResource = async (resourceId: ManagedModelResourceId) => {
  switch (resourceId) {
    case 'sherpa_online':
      await runResourceCommand('sherpa-online-download', () => resourceClient.prepareSherpaOnline(), [resourceId])
      break
    case 'soulx':
      await runResourceCommand('soulx-download', () => resourceClient.prepareSoulx(), [resourceId])
      break
    case 'sherpa':
      await runResourceCommand('sherpa-download', () => resourceClient.prepareSherpa(), [resourceId])
      break
    case 'embedding':
      await runResourceCommand('embedding-prefetch', () => resourceClient.prepareEmbedding(), [resourceId])
      break
    case 'tts':
      await runResourceCommand('tts-prefetch', () => resourceClient.prepareTts(), [resourceId])
      break
  }
}

const importSoulxReference = () => runResourceCommand(
  'soulx-reference',
  () => resourceClient.importSoulxReference(),
)

const removeModelResource = async (
  resourceId: ManagedModelResourceId,
  label: string,
  metadata: ManagedResourceMetadata,
) => {
  if (resourceActionKey.value || activeDownloadProgress.value.length || cancellingResourceIds.value.length || resourceStateUncertain) {
    ElMessage.warning(t('settingsPanel.message.finishCurrentResourceTask'))
    return
  }
  const usage = metadata.inUseBy.length > 0
    ? t('settingsPanel.message.inUseSuffix', { list: metadata.inUseBy.join(' / ') })
    : ''
  try {
    await ElMessageBox.confirm(
      `${label} · ${formatResourceDownloadBytes(metadata.downloadBytes)}${usage}`,
      t('settingsPanel.removeModelTitle'),
      {
        confirmButtonText: t('settingsPanel.removeModelConfirm'),
        cancelButtonText: t('common.cancel'),
        type: 'warning',
      },
    )
  } catch {
    return
  }

  if (resourceActionKey.value || activeDownloadProgress.value.length || cancellingResourceIds.value.length || resourceStateUncertain) return
  resourceStatusVersion += 1
  resourceActionKey.value = `remove-${resourceId}`
  try {
    const result = await resourceClient.remove([resourceId])
    resourceStatusVersion += 1
    resourceStatus.value = normalizeResourceStatus(result.status)
    const skipped = [resourceId].filter((id) => !result.removed.includes(id) && !result.failed.some((item) => item.resourceId === id))
    resourceMessage.value = t('settings.resource.removalResult', {
      removed: result.removed.join(' / ') || '—',
      skipped: skipped.join(' / ') || '—',
      failed: result.failed.map((item) => item.resourceId + ': ' + item.reason).join('; ') || '—',
    })
    resourceMessageType.value = result.success ? 'success' : 'warning'
    if (result.success) {
      ElMessage.success(t('settingsPanel.message.removeModelOk', {
        label,
        size: formatStorageBytes(result.reclaimedBytes),
      }))
    } else {
      ElMessage.warning(result.failed.map((item) => item.reason).join('; ') || result.message)
    }
  } catch (error) {
    ElMessage.error(describeFailure(error, t('settings.resource.taskFailed')))
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
    ElMessage.error(describeFailure(error, t('settings.storage.loadFailed')))
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
  if (asr?.provider === 'sherpa-onnx-online') ids.push('sherpa_online', 'sherpa')
  if (asr?.provider === 'sherpa-onnx') ids.push('sherpa')
  if (tts && (tts.provider ?? form.tts.provider) === TTS_PROVIDER) ids.push('tts')
  if (svc?.provider === 'soulx-service') ids.push('soulx')
  if (typeof memory?.embedding_model === 'string') ids.push('embedding')
  return [...new Set(ids)]
}

const prepareResourcesForSettingsPatch = async (patch: SettingsPatch) => {
  const ids = resourceIdsForSettingsPatch(patch).filter((id) => !resourceDownloadOptions.value.find((item) => item.id === id)?.ready)
  if (ids.length === 0) return
  await runResourceCommand('first-use-download', () => resourceClient.prepare(ids), ids)
}

const downloadSelectedResources = async () => {
  const requiredMissing = resourceDownloadOptions.value
    .filter((item) => item.requiredOnFirstRun && !item.ready)
    .map((item) => item.id)
  const ids = [...new Set([...selectedResourceIds.value, ...requiredMissing])]
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
    ElMessage.error(describeFailure(error, t('settings.storage.cleanFailed')))
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
  if (!options?.manual && !isSectionVisible('llm')) return
  if (modelDiscoveryTimeout) clearTimeout(modelDiscoveryTimeout)
  modelDiscoveryTimeout = null
  if (!(await flushPendingSave()) || unmounted) return
  if (!options?.manual && !isSectionVisible('llm')) return
  const baseUrl = normalizeOpenAiBaseUrl(form.llm.base_url)
  const provider = llmProviderPreset.value
  const apiKey = llmProviderNeedsApiKey.value
    ? (form.llm.api_key.trim() || (llmApiKeyStored.value ? SETTINGS_SECRET_MASK : ''))
    : ''
  const timeout = form.llm.timeout
  const modelBeforeLookup = form.llm.model
  const discoveryKey = llmModelDiscoveryKey()
  if (!options?.manual && activeLlmModelDiscoveryKey === discoveryKey && llmModelsRequest.loading) return
  const runId = ++modelDiscoveryRun
  activeLlmModelDiscoveryKey = discoveryKey
  if (!baseUrl) {
    activeLlmModelDiscoveryKey = null
    llmModels.value = []
    llmModelStatus.value = ''
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }
  if (!options?.manual && !canAutoDiscoverLlmModels.value) {
    activeLlmModelDiscoveryKey = null
    llmModels.value = []
    llmModelStatus.value = t('settings.llm.modelsSkippedNoKey')
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    return
  }

  const result = await loadLlmModels({
    provider,
    base_url: baseUrl,
    api_key: apiKey,
    timeout,
  })
  const currentApiKey = llmProviderNeedsApiKey.value
    ? (form.llm.api_key.trim() || (llmApiKeyStored.value ? SETTINGS_SECRET_MASK : ''))
    : ''
  if (
    runId !== modelDiscoveryRun
    || provider !== llmProviderPreset.value
    || baseUrl !== normalizeOpenAiBaseUrl(form.llm.base_url)
    || apiKey !== currentApiKey
    || timeout !== form.llm.timeout
  ) return

  activeLlmModelDiscoveryKey = null
  lastLlmModelDiscoveryKey = discoveryKey

  if (result?.ok) {
    llmModels.value = result.models
    if (form.llm.model === modelBeforeLookup) applyDetectedLlmModel(result.models, options)
    llmModelStatus.value = result.models.length
      ? t('settings.llm.modelsDetected', {
        count: result.models.length,
        selected: llmModelAutoSelected.value ? t('settings.llm.modelsSelected', { model: form.llm.model }) : '',
      })
      : (result.message || t('settings.llm.modelsEmpty'))
  } else if (result) {
    llmModels.value = []
    llmModelStatus.value = result.message || t('settings.llm.modelsFailed')
    llmModelAutoSelected.value = false
  }
}

const scheduleLlmModelDiscovery = (options?: LlmModelDiscoveryOptions) => {
  if (suppressModelDiscovery || (!options?.manual && !isSectionVisible('llm'))) return
  const discoveryKey = llmModelDiscoveryKey()
  if (
    !options?.manual
    && (discoveryKey === lastLlmModelDiscoveryKey
      || discoveryKey === activeLlmModelDiscoveryKey
      || discoveryKey === scheduledLlmModelDiscoveryKey)
  ) return
  invalidateLlmModelDiscovery()
  if (!normalizeOpenAiBaseUrl(form.llm.base_url)) {
    llmModels.value = []
    llmModelStatus.value = ''
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    lastLlmModelDiscoveryKey = discoveryKey
    return
  }
  if (!options?.manual && !canAutoDiscoverLlmModels.value) {
    llmModels.value = []
    llmModelStatus.value = t('settings.llm.modelsSkippedNoKey')
    llmModelAutoSelected.value = false
    llmModelsRequest.reset()
    lastLlmModelDiscoveryKey = discoveryKey
    return
  }
  scheduledLlmModelDiscoveryKey = discoveryKey
  modelDiscoveryTimeout = setTimeout(() => {
    modelDiscoveryTimeout = null
    scheduledLlmModelDiscoveryKey = null
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
  if (form.llm.api_key.trim()) llmApiKeyStored.value = true
  saveLlmField(field, form.llm.api_key)
  if (field === 'api_key') {
    invalidateLlmModelDiscovery()
    modelDiscoveryTimeout = setTimeout(async () => {
      modelDiscoveryTimeout = null
      await discoverLlmModels({ manual: false })
    }, 700)
    return
  }
  scheduleLlmModelDiscovery({ manual: false })
}

const finishKeyOperation = () => {
  if (keyMutationAcquired) finishSettingsMutation()
  keyMutationAcquired = false
  keyOperation.value = ''
}

const refreshSettingsPreservingDraft = async (before: ReturnType<typeof captureFormDraft>, updatedKey?: string) => {
  const normalized = await loadSettings()
  if (!normalized) throw new Error([t('settings.messages.readbackFailed'), settingsRequest.error].filter(Boolean).join(' '))
  for (const [section, values] of Object.entries(normalized)) {
    const target = settingsStore.state[section as keyof typeof settingsStore.state]
    if (target && typeof target === 'object' && isPlainRecord(values)) Object.assign(target, values)
  }
  const submitted = updatedKey
    ? updatedKey.split('.').reduceRight<unknown>((value, part) => ({ [part]: value }), settingValueAt(normalized, updatedKey)) as SettingsPatch
    : {}
  saveQueue.completion.value = { status: 'ok', normalizedSettings: normalized, submitted, owner: saveOwner }
  hydratePreservingDraft(before, normalized, submitted, true)
  await loadSettingsAdmin()
}

const readSettingKey = async () => {
  const key = lookupKey.value.trim()
  if (!key || keyOperation.value) return
  keyOperation.value = 'read'
  keyError.value = ''
  lookupResult.value = ''
  try {
    const result = await settingsClient.getSetting(key)
    if (key === lookupKey.value.trim()) lookupResult.value = JSON.stringify(result, null, 2)
  } catch (error) {
    keyError.value = describeFailure(error, t('common.error.unknown'))
  } finally {
    finishKeyOperation()
  }
}

const writeSettingKey = async () => {
  const key = setKey.value.trim()
  if (!key || keyOperation.value) return
  keyError.value = ''
  let value: unknown
  try {
    value = parseSettingInput(setValueJson.value, setValueMode.value, settingValueAt(settings.value, key))
  } catch (error) {
    keyError.value = t(error instanceof SyntaxError ? 'settings.key.invalidJson' : 'settings.key.invalidType')
    return
  }
  keyOperation.value = 'write'
  try {
    keyMutationAcquired = await beginSettingsMutation()
    if (!keyMutationAcquired) {
      keyError.value = t('settings.messages.saveFailed')
      return
    }
    const before = captureFormDraft()
    const result = await settingsClient.setSetting(key, value)
    await refreshSettingsPreservingDraft(before, key)
    recordSettingsSaved(result)
    ElMessage.success(t('settings.messages.settingWritten'))
  } catch (error) {
    keyError.value = describeFailure(error, t('common.error.unknown'))
  } finally {
    finishKeyOperation()
  }
}

const resetSettingKey = async () => {
  const key = deleteKey.value.trim()
  if (!key || keyOperation.value) return
  keyOperation.value = 'reset'
  keyError.value = ''
  try {
    await ElMessageBox.confirm(
      t('settings.confirm.deleteKeyMessage', { key }),
      t('settings.confirm.deleteKeyTitle'),
      { confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'), type: 'warning' },
    )
  } catch {
    finishKeyOperation()
    return
  }
  const sensitive = ['llm.api_key', 'llm.vision_api_key', 'tts.api_key', 'asr.api_key', 'memory.qdrant_api_key'].includes(key)
  if (sensitive && isSensitiveDeleting(key)) {
    keyError.value = t('settings.status.saving')
    finishKeyOperation()
    return
  }
  if (sensitive) {
    setSensitiveDeleting(key, true)
    pendingSavePatch.value = stripPatchPath(pendingSavePatch.value, key)
    failedSavePatch.value = stripPatchPath(failedSavePatch.value, key)
  }
  try {
    keyMutationAcquired = await beginSettingsMutation()
    if (!keyMutationAcquired) {
      keyError.value = t('settings.messages.saveFailed')
      return
    }
    const before = captureFormDraft()
    const result = await settingsClient.deleteSetting(key)
    if (sensitive) publishCredentialDeletion(key)
    await refreshSettingsPreservingDraft(before, key)
    recordSettingsSaved(result)
    ElMessage.success(t('settings.messages.settingReset'))
    if (deleteKey.value.trim() === key) deleteKey.value = ''
  } catch (error) {
    keyError.value = describeFailure(error, t('common.error.unknown'))
  } finally {
    finishKeyOperation()
    if (sensitive) setSensitiveDeleting(key, false)
  }
}

const hydrateForm = (s = settings.value) => {
  if (!s) return
  suppressModelDiscovery = true
  const migrationVersionKey = 'yuizaki.llm.inference-defaults-version'
  const shouldMigrateLegacyDefaults = window.localStorage.getItem(migrationVersionKey) !== 'gpt-6.1-sol-v1'
  let migratedLegacyDefaults = false

  if (s.llm) {
    clearReactiveRecord(llmProfiles as Record<string, unknown>)
    for (const [key, profile] of Object.entries(s.llm.profiles || {})) {
      const provider = normalizeLlmProviderValue(key, profile?.base_url || '')
      const normalizedProfile = sanitizeLlmProfile(provider, profile as Partial<LlmProfile>)
      const migrationPatch = shouldMigrateLegacyDefaults
        ? migrateLegacyLlmDefaults(normalizedProfile as unknown as Record<string, unknown>)
        : {}
      Object.assign(normalizedProfile, migrationPatch)
      migratedLegacyDefaults ||= Object.keys(migrationPatch).length > 0
      llmProfiles[provider] = normalizedProfile
    }
    const activeProvider = normalizeLlmProviderValue(s.llm.provider, s.llm.base_url)
    const normalizedActiveProfile = sanitizeLlmProfile(activeProvider, {
      ...(llmProfiles[activeProvider] || {}),
      provider: activeProvider,
      base_url: s.llm.base_url ?? '',
      api_key: s.llm.api_key ?? '',
      model: s.llm.model ?? '',
      temperature: s.llm.temperature ?? DEFAULT_LLM_TEMPERATURE,
      top_p: s.llm.top_p ?? DEFAULT_LLM_TOP_P,
      top_k: s.llm.top_k ?? DEFAULT_LLM_TOP_K,
      min_p: s.llm.min_p ?? DEFAULT_LLM_MIN_P,
      frequency_penalty: s.llm.frequency_penalty ?? DEFAULT_LLM_FREQUENCY_PENALTY,
      presence_penalty: s.llm.presence_penalty ?? DEFAULT_LLM_PRESENCE_PENALTY,
      repetition_penalty: s.llm.repetition_penalty ?? DEFAULT_LLM_REPETITION_PENALTY,
      timeout: s.llm.timeout ?? DEFAULT_LLM_TIMEOUT_SECONDS,
      context_max_tokens: s.llm.context_max_tokens ?? DEFAULT_LLM_CONTEXT_MAX_TOKENS,
      default_max_output_tokens: s.llm.default_max_output_tokens ?? DEFAULT_LLM_MAX_OUTPUT_TOKENS,
    })
    const activeMigrationPatch = shouldMigrateLegacyDefaults
      ? migrateLegacyLlmDefaults(normalizedActiveProfile as unknown as Record<string, unknown>) as Partial<LlmProfile>
      : {}
    const activeProfile = { ...normalizedActiveProfile, ...activeMigrationPatch }
    migratedLegacyDefaults ||= Object.keys(activeMigrationPatch).length > 0
    llmProfiles[activeProvider] = activeProfile
    llmProviderPreset.value = activeProvider
    applyLlmProfileToForm(activeProfile)
    form.llm.vision_enabled = s.llm.vision_enabled ?? false
    form.llm.vision_provider = normalizeLlmProviderValue(s.llm.vision_provider, s.llm.vision_base_url)
    form.llm.vision_base_url = s.llm.vision_base_url ?? ''
    const visionApiKey = s.llm.vision_api_key ?? ''
    visionApiKeyStored.value = Boolean(visionApiKey)
    form.llm.vision_api_key = visionApiKey === SETTINGS_SECRET_MASK ? '' : visionApiKey
    form.llm.vision_model = s.llm.vision_model ?? ''
    form.llm.vision_timeout = s.llm.vision_timeout ?? 30
    form.llm.vision_detail = s.llm.vision_detail ?? 'low'
    llmModelAutoSelected.value = false
    if (shouldMigrateLegacyDefaults) {
      if (migratedLegacyDefaults) saveActiveLlmPatch(activeMigrationPatch)
      window.localStorage.setItem(migrationVersionKey, 'gpt-6.1-sol-v1')
    }
  }

  if (s.tts) {
    const ttsApiKey = s.tts.api_key || ''
    const ttsMasked = ttsApiKey === SETTINGS_SECRET_MASK
    ttsApiKeyStored.value = ttsMasked || Boolean(ttsApiKey.trim())
    const activeProfile = sanitizeTtsProfile({
      genie_character: s.tts.genie_character ?? '',
      genie_model_dir: s.tts.genie_model_dir || '',
      ref_audio: s.tts.ref_audio ?? '',
      ref_text: s.tts.ref_text ?? '',
      lang: s.tts.lang || 'ja',
      device: s.tts.device || 'cpu',
      quality: s.tts.quality || TTS_CONTRACT_VALUES.qualityFirst,
      split: s.tts.split || TTS_CONTRACT_VALUES.splitSmart,
      mode: s.tts.mode || TTS_CONTRACT_VALUES.modeSerial,
      save_mode: s.tts.save_mode || TTS_CONTRACT_VALUES.saveModeDisabled,
      provider: s.tts.provider === 'openai-compatible' ? 'openai-compatible' : TTS_PROVIDER,
      base_url: s.tts.base_url || '',
      api_key: ttsMasked ? '' : ttsApiKey,
      model: s.tts.model || 'tts-1',
      voice: s.tts.voice || 'alloy',
      timeout: s.tts.timeout ?? 60,
    })
    applyTtsProfileToForm(activeProfile)
  }

  if (s.asr) {
    const asrApiKey = s.asr.api_key || ''
    asrApiKeyStored.value = asrApiKey === SETTINGS_SECRET_MASK || Boolean(asrApiKey.trim())
    form.asr.provider = s.asr.provider || 'sherpa-onnx'
    form.asr.base_url = s.asr.base_url ?? ''
    form.asr.api_key = asrApiKey === SETTINGS_SECRET_MASK ? '' : asrApiKey
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
    const memoryApiKey = s.memory.qdrant_api_key ?? ''
    memoryApiKeyStored.value = memoryApiKey === SETTINGS_SECRET_MASK || Boolean(memoryApiKey.trim())
    form.memory.qdrant_api_key = memoryApiKey === SETTINGS_SECRET_MASK ? '' : memoryApiKey
    form.memory.qdrant_collection = s.memory.qdrant_collection ?? 'memories'
    form.memory.qdrant_timeout = s.memory.qdrant_timeout ?? 10
    form.memory.qdrant_auto_start = s.memory.qdrant_auto_start ?? false
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

const runtimeFailedSections = computed(() => Object.entries(runtimeReload.value?.sections || {})
  .filter(([, status]) => status.state === 'failed' || status.state === 'unavailable').map(([section]) => section))
let runtimeStatusTimer: ReturnType<typeof setTimeout> | null = null
let settingsActive = true
let initialActivation = true
const isSectionVisible = (section: SettingSectionId) => settingsActive && !unmounted && !document.hidden && activeSection.value === section

const stopRuntimeStatusPoll = () => {
  if (runtimeStatusTimer !== null) clearTimeout(runtimeStatusTimer)
  runtimeStatusTimer = null
}
const observedServiceTargets = new Map<string, number>()
const refreshedServiceTargets = new Map<string, number>()
const syncRuntimeReloadDisplay = () => {
  for (const section of ['llm', 'tts']) {
    const status = runtimeReload.value?.sections[section]
    if (!status) continue
    if (observedServiceTargets.get(section) !== status.target_revision) {
      observedServiceTargets.set(section, status.target_revision)
      if (section === 'llm') { llmStatusRequest.reset(); llmStatus.value = null }
      else { ttsStatusRequest.reset(); ttsStatus.value = null }
    }
    if (isSectionVisible(section === 'llm' ? 'llm' : 'voice') && status.state === 'applied' && status.applied_revision === status.target_revision && refreshedServiceTargets.get(section) !== status.target_revision) {
      refreshedServiceTargets.set(section, status.target_revision)
      if (section === 'llm') void loadLlmStatus()
      else void loadTtsStatus()
    }
  }
  const entries = Object.entries(runtimeReload.value?.sections || {})
  lastApplied.value = entries.filter(([, status]) => status.state === 'applied' && status.applied_revision === status.target_revision).map(([section]) => section)
  lastRuntimePending.value = entries.filter(([, status]) => status.state === 'pending' || status.state === 'applying').map(([section]) => section)
}
const scheduleRuntimeStatusPoll = () => {
  stopRuntimeStatusPoll()
  if (!settingsActive || unmounted || document.hidden || !lastRuntimePending.value.length || runtimeStatusRequest.error) return
  runtimeStatusTimer = setTimeout(() => void refreshRuntimeApplication(), 1000)
}
const refreshRuntimeApplication = async () => {
  if (!settingsActive || unmounted || document.hidden || runtimeStatusRequest.loading || runtimeRetryRequest.loading) return
  await loadRuntimeStatus()
  if (unmounted) return
  syncRuntimeReloadDisplay()
  scheduleRuntimeStatusPoll()
}
const loadPanelSettings = async () => {
  const completionBefore = saveQueue.completion.value
  const loaded = await loadSettings()
  // A write from another panel may finish while this GET is still returning an older snapshot.
  const completion = saveQueue.completion.value
  if (completion && completion !== completionBefore) {
    settings.value = completion.normalizedSettings
    return completion.normalizedSettings
  }
  return loaded
}
const refreshActivatedSettings = async () => {
  if (!settingsActive || unmounted || document.hidden) return
  if (saveQueue.adminInFlight) await new Promise<void>((resolve) => saveQueue.adminResolvers.push(resolve))
  if (saveInFlight.value) await waitForSaveIdle()
  if (!settingsActive || unmounted || document.hidden) return
  const before = captureFormDraft()
  const loaded = await loadPanelSettings()
  if (!loaded || unmounted) return
  hydratePreservingDraft(before, loaded)
}

// Only the visible subpage starts auxiliary requests. Deduplicate overlapping
// mount/route/activation notifications without serializing unrelated subpages.
const sectionRequests = new Map<SettingSectionId, Promise<unknown>>()
const refreshActiveSection = (): Promise<unknown> => {
  const section = activeSection.value
  if (!settings.value || settingsRequest.loading || !isSectionVisible(section)) return Promise.resolve()
  const existing = sectionRequests.get(section)
  if (existing) return existing
  const request = (async () => {
    switch (section) {
      case 'access':
        await refreshBackendTokenStatus()
        break
      case 'llm':
        scheduleLlmModelDiscovery({ manual: false })
        await Promise.all([refreshRuntimeApplication(), loadLlmStatus()])
        break
      case 'voice':
        await Promise.all([refreshRuntimeApplication(), loadTtsStatus(), loadGenieCharacters()])
        if (isSectionVisible('voice')) await queueTtsWarmup()
        break
      case 'memory':
        await Promise.all([refreshMemoryIndexStatus(), memoryIndexWorking.value ? refreshMemoryRebuild() : undefined])
        break
      case 'resources':
        await refreshResourcePanel()
        break
      case 'system':
        await Promise.all([inputBindingsStore.load(), adminCollapseNames.value.includes('metadata') ? loadSettingsAdmin() : undefined])
        break
      case 'svc':
      case 'runtime-guide':
        await refreshRuntimeApplication()
        break
    }
  })().catch((error) => console.info('[Settings] Section refresh unavailable:', error))
    .finally(() => { sectionRequests.delete(section) })
  sectionRequests.set(section, request)
  return request
}

watch(saveQueue.completion, (result) => {
  if (!result || unmounted || result.owner === saveOwner) return
  const before = captureFormDraft()
  settings.value = result.normalizedSettings
  hydratePreservingDraft(before, result.normalizedSettings, acknowledgedSubmission(result.submitted, result.fields || new Map()))
  finishSubmission(result.fields || new Map(), result.recoveredFailures || new Set())
  for (const key of result.deletedKeys || []) clearDeletedCredentialDraft(key)
  recordSettingsSaved(result)
}, { flush: 'sync' })

const retryRuntimeApplication = async (targets: Record<string, number>) => {
  // Freeze target revisions in the feedback component; the backend rejects stale retries.
  const result = await retryRuntime({ ...targets })
  if (!result || unmounted) return
  syncRuntimeReloadDisplay()
  scheduleRuntimeStatusPoll()
}

watch(runtimeReload, () => {
  syncRuntimeReloadDisplay()
  scheduleRuntimeStatusPoll()
})
onActivated(() => {
  settingsActive = true
  if (initialActivation) {
    initialActivation = false
    return
  }
  syncSectionFromRoute()
  void refreshActivatedSettings().then(() => {
    void refreshRuntimeApplication()
    return refreshActiveSection()
  })
})
onDeactivated(() => {
  settingsActive = false
  invalidateLlmModelDiscovery({ preserveLast: true })
  stopRuntimeStatusPoll()
  stopResourceProgressPolling()
  stopMemoryRebuildPolling()
})

onMounted(async () => {
  syncSectionFromRoute()
  const before = captureFormDraft()
  document.addEventListener('visibilitychange', handleResourceProgressVisibility)
  const loaded = await loadPanelSettings()
  if (!loaded || unmounted) return
  hydratePreservingDraft(before, loaded)
  void refreshRuntimeApplication()
  void refreshActiveSection()
})

onBeforeUnmount(() => {
  if (saveQueue.timeout) {
    clearTimeout(saveQueue.timeout)
    saveQueue.timeout = null
  }
  promoteFailedSavePatch()
  if (pendingSavePatch.value) {
    void drainSaveQueue()
  }
})

onUnmounted(() => {
  unmounted = true
  stopRuntimeStatusPoll()
  if (modelDiscoveryTimeout) clearTimeout(modelDiscoveryTimeout)
  modelDiscoveryTimeout = null
  stopResourceProgressPolling()
  stopMemoryRebuildPolling()
  document.removeEventListener('visibilitychange', handleResourceProgressVisibility)
  notifySaveIdle()
})

watch(lookupKey, () => { lookupResult.value = '' })
watch([lookupKey, setKey, setValueJson, setValueMode, deleteKey], () => { keyError.value = '' })

watch(currentLocale, (value) => {
  form.system.language = value
})

watch(() => route.query.section, syncSectionFromRoute)

watch(activeSection, () => {
  invalidateLlmModelDiscovery({ preserveLast: true })
  stopResourceProgressPolling()
  stopMemoryRebuildPolling()
  void refreshActiveSection()
})

watch(adminCollapseNames, (names) => {
  if (isSectionVisible('system') && names.includes('metadata')) void loadSettingsAdmin()
})

</script>

<style scoped src="./SettingsPanel.css"></style>
