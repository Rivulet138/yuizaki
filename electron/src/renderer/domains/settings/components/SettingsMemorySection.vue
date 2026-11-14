<template>
  <el-card shadow="never">
    <template #header>
      <SettingsSectionHeader :title="t('settings.memory.title')">
        <template #status>
          <el-tag size="small" type="success" effect="plain">{{ t('settings.memory.localAuthority') }}</el-tag>
          <el-tag size="small" type="info" effect="plain">{{ backendLabel }}</el-tag>
        </template>
        <template #actions>
          <el-button data-testid="discover-memory" plain :loading="discoveryLoading" @click="$emit('discover-local')">
            <el-icon><Connection /></el-icon>
            {{ t('settings.discovery.detectLocal') }}
          </el-button>
          <el-button
            data-testid="rebuild-memory"
            type="primary"
            plain
            :loading="rebuildLoading"
            :disabled="modelValue.backend === 'inmemory'"
            @click="$emit('rebuild')"
          >
            <el-icon><Refresh /></el-icon>
            {{ t('settings.memory.rebuildIndex') }}
          </el-button>
        </template>
      </SettingsSectionHeader>
    </template>

    <el-alert v-if="indexStatusError" :title="indexStatusError" type="error" :closable="false" show-icon />
    <div class="button-row" role="status">
      <span>{{ t('settings.memory.actualBackend') }}: {{ indexStatus?.backend || t('settings.memory.unknown') }}</span>
      <el-tag :type="indexStatusError ? 'danger' : indexStatus?.healthy === true ? 'success' : indexStatus?.healthy === false ? 'warning' : 'info'">
        {{ t(indexStatusError ? 'settings.memory.statusFailed' : indexStatus?.healthy === true ? 'settings.memory.healthy' : indexStatus?.healthy === false ? 'settings.memory.unhealthy' : 'settings.memory.unknown') }}
      </el-tag>
      <span v-if="indexStatus">{{ t('settings.memory.documentCount', { count: indexStatus.count }) }}</span>
      <el-button plain :loading="indexStatusLoading" :disabled="rebuildLoading" @click="$emit('refresh-status')">{{ t('common.refresh') }}</el-button>
    </div>
    <div v-if="indexStatus" class="button-row" role="status">
      <span>{{ t('settings.memory.authorityRevision') }}: {{ indexStatus.metadata?.authority_revision ?? t('settings.memory.revisionUnavailable') }}</span>
      <span>{{ t('settings.memory.indexGeneration') }}: {{ indexStatus.metadata?.index_generation ?? t('settings.memory.revisionUnavailable') }}</span>
      <span>{{ t('settings.memory.indexSnapshotRevision') }}: {{ indexStatus.metadata?.index_snapshot_revision ?? t('settings.memory.revisionUnavailable') }}</span>
    </div>
    <p v-if="indexStatus?.message">{{ indexStatus.message }}</p>
    <el-alert v-if="rebuildError" :title="rebuildError" type="error" :closable="false" show-icon />
    <div v-if="rebuildJob" class="button-row" role="status">
      <el-tag :type="rebuildJob.state === 'completed' ? 'success' : ['failed', 'interrupted'].includes(rebuildJob.state) ? 'danger' : 'info'">
        {{ t('settings.memory.rebuildState.' + rebuildJob.state) }} · {{ rebuildJob.processed_count }} / {{ rebuildJob.total_count }}
      </el-tag>
      <el-button plain :loading="rebuildRefreshing" :disabled="rebuildCancelling" @click="$emit('refresh-rebuild')">{{ t('common.refresh') }}</el-button>
      <el-button v-if="['queued', 'running', 'cancelling'].includes(rebuildJob.state)" plain :loading="rebuildCancelling" :disabled="rebuildJob.state === 'cancelling' || rebuildRefreshing" @click="$emit('cancel-rebuild')">{{ t('common.cancel') }}</el-button>
    </div>

    <el-form class="memory-settings" label-position="top" @submit.prevent>
      <section class="settings-block" aria-labelledby="memory-storage-heading">
        <div class="block-heading">
          <div>
            <h4 id="memory-storage-heading">{{ t('settings.memory.storageTitle') }}</h4>
          </div>
        </div>
        <el-form-item :label="t('settings.memory.backend')">
          <el-radio-group class="backend-selector" :model-value="modelValue.backend" @change="$emit('change-backend', String($event))">
            <el-radio-button value="sqlite">SQLite</el-radio-button>
            <el-radio-button value="inmemory">{{ t('settings.memory.backendInMemory') }}</el-radio-button>
            <el-radio-button value="qdrant">{{ t('settings.memory.backendQdrant') }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="modelValue.backend === 'sqlite'" :label="t('settings.memory.sqlitePath')">
          <el-input
            :model-value="modelValue.sqlite_path"
            placeholder="python/data/memory.db"
            @change="emitField('sqlite_path', $event)"
          />
        </el-form-item>
      </section>

      <section class="settings-block" aria-labelledby="memory-search-heading">
        <div class="block-heading">
          <div>
            <h4 id="memory-search-heading">{{ t('settings.memory.semanticTitle') }}</h4>
          </div>
          <el-switch
            :model-value="modelValue.reranker_enabled"
            :aria-label="t('settings.memory.rerankerEnabled')"
            @change="emitField('reranker_enabled', $event)"
          />
        </div>
        <el-form-item :label="t('settings.memory.embedding')">
          <el-input
            :model-value="modelValue.embedding_model"
            :placeholder="defaultEmbeddingModel"
            @change="emitField('embedding_model', $event)"
          />
        </el-form-item>
        <div v-if="modelValue.reranker_enabled" class="form-grid">
          <el-form-item :label="t('settings.memory.rerankerModel')">
            <el-input :model-value="modelValue.reranker_model" @change="emitField('reranker_model', $event)" />
          </el-form-item>
          <el-form-item :label="t('settings.memory.rerankerCandidates')">
            <el-input-number
              :model-value="modelValue.reranker_candidate_count"
              :min="5"
              :max="100"
              :step="5"
              controls-position="right"
              @change="emitField('reranker_candidate_count', $event)"
            />
          </el-form-item>
        </div>
      </section>

      <section v-if="modelValue.backend === 'qdrant'" class="settings-block" aria-labelledby="memory-qdrant-heading">
        <div class="block-heading">
          <div>
            <h4 id="memory-qdrant-heading">Qdrant</h4>
          </div>
        </div>
        <div class="form-grid">
          <el-form-item :label="t('settings.memory.qdrantUrl')">
            <el-input :model-value="modelValue.qdrant_url" @change="emitField('qdrant_url', $event)" />
          </el-form-item>
          <el-form-item :label="t('settings.memory.qdrantApiKey')">
            <el-input :model-value="modelValue.qdrant_api_key" :disabled="apiKeyDeleting" type="password" show-password @change="emitField('qdrant_api_key', $event)">
              <template #append>
              <el-button v-if="modelValue.qdrant_api_key || apiKeyStored" text type="danger" :loading="apiKeyDeleting" :disabled="apiKeyDeleting" @click="$emit('clear-api-key')">{{ t('settings.apiKeyClear') }}</el-button>
              </template>
            </el-input>
          </el-form-item>
          <el-form-item :label="t('settings.memory.collection')">
            <el-input :model-value="modelValue.qdrant_collection" placeholder="memories" @change="emitField('qdrant_collection', $event)" />
          </el-form-item>
          <el-form-item :label="t('settings.memory.qdrantTimeout')">
            <el-input-number :model-value="modelValue.qdrant_timeout" :min="0.1" :max="300" :step="1" @change="emitField('qdrant_timeout', $event)" />
          </el-form-item>
        </div>
        <el-form-item :label="t('settings.memory.qdrantAutoStart')">
          <el-switch :model-value="modelValue.qdrant_auto_start" @change="emitField('qdrant_auto_start', $event)" />
        </el-form-item>
        <div v-if="modelValue.qdrant_auto_start" class="form-grid three">
          <el-form-item :label="t('settings.memory.qdrantDockerImage')">
            <el-input :model-value="modelValue.qdrant_docker_image" :placeholder="defaultQdrantDockerImage" @change="emitField('qdrant_docker_image', $event)" />
          </el-form-item>
          <el-form-item :label="t('settings.memory.qdrantDockerContainer')">
            <el-input :model-value="modelValue.qdrant_docker_container" placeholder="yuizaki-qdrant" @change="emitField('qdrant_docker_container', $event)" />
          </el-form-item>
          <el-form-item :label="t('settings.memory.qdrantDockerVolume')">
            <el-input :model-value="modelValue.qdrant_docker_volume" placeholder="yuizaki-qdrant-storage" @change="emitField('qdrant_docker_volume', $event)" />
          </el-form-item>
        </div>
      </section>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import type { MemoryIndexRebuildJob, MemoryIndexStatus } from '@/api/clients/memory-client'
import { ElAlert } from 'element-plus'
import 'element-plus/es/components/alert/style/css'
import { ElIcon } from 'element-plus'
import 'element-plus/es/components/icon/style/css'
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElSwitch } from 'element-plus'
import 'element-plus/es/components/switch/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { ElCard } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
import { computed } from 'vue'
import { Connection, Refresh } from '@element-plus/icons-vue'
import { ElRadioButton, ElRadioGroup } from 'element-plus'
import { ElForm, ElFormItem } from 'element-plus'
import 'element-plus/es/components/radio-button/style/css'
import 'element-plus/es/components/radio-group/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'

import { t } from '@/i18n'
import SettingsSectionHeader from './SettingsSectionHeader.vue'

export type MemorySettings = {
  backend: string
  sqlite_path: string
  qdrant_url: string
  qdrant_api_key: string
  qdrant_collection: string
  qdrant_timeout: number
  qdrant_auto_start: boolean
  qdrant_docker_image: string
  qdrant_docker_container: string
  qdrant_docker_volume: string
  embedding_model: string
  reranker_enabled: boolean
  reranker_model: string
  reranker_candidate_count: number
}

type MemorySettingValue = MemorySettings[keyof MemorySettings]

const props = defineProps<{
  modelValue: MemorySettings
  discoveryLoading: boolean
  rebuildLoading: boolean
  indexStatus?: MemoryIndexStatus | null
  indexStatusLoading?: boolean
  indexStatusError?: string
  rebuildJob?: MemoryIndexRebuildJob | null
  rebuildError?: string
  rebuildRefreshing?: boolean
  rebuildCancelling?: boolean
  defaultEmbeddingModel?: string
  defaultQdrantDockerImage?: string
  apiKeyStored?: boolean
  apiKeyDeleting?: boolean
}>()

const backendLabel = computed(() => ({
  sqlite: 'SQLite',
  inmemory: 'In-memory',
  qdrant: 'SQLite + Qdrant',
}[props.modelValue.backend] || props.modelValue.backend))

const emit = defineEmits<{
  'update-field': [field: keyof MemorySettings, value: MemorySettingValue]
  'change-backend': [backend: string]
  'discover-local': []
  'clear-api-key': []
  rebuild: []
  'refresh-status': []
  'refresh-rebuild': []
  'cancel-rebuild': []
}>()

const emitField = (field: keyof MemorySettings, value: unknown) => {
  if (typeof value === 'string' || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value))) {
    emit('update-field', field, value)
  }
}
</script>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
  min-width: 0;
}

.memory-settings {
  display: grid;
  gap: 0;
}

.settings-block {
  padding: 18px 0;
  border-bottom: 1px solid var(--yui-border);
}

.settings-block:first-child {
  padding-top: 2px;
}

.settings-block:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.block-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.block-heading h4 {
  margin: 0;
}

.block-heading h4 {
  color: var(--yui-text);
  font-size: 14px;
  font-weight: 700;
}

.backend-selector {
  max-width: 100%;
}

.form-grid.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

@media (max-width: 900px) {
  .form-grid,
  .form-grid.three {
    grid-template-columns: minmax(0, 1fr);
  }

  .block-heading {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
