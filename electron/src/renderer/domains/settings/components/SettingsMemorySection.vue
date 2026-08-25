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

    <el-form class="memory-settings" label-position="top" @submit.prevent>
      <section class="settings-block" aria-labelledby="memory-storage-heading">
        <div class="block-heading">
          <div>
            <h4 id="memory-storage-heading">{{ t('settings.memory.storageTitle') }}</h4>
            <p>{{ t('settings.memory.storageDescription') }}</p>
          </div>
        </div>
        <el-form-item :label="t('settings.memory.backend')">
          <el-radio-group class="backend-selector" :model-value="modelValue.backend" @change="$emit('change-backend', String($event))">
            <el-radio-button value="sqlite">SQLite</el-radio-button>
            <el-radio-button value="inmemory">In-memory</el-radio-button>
            <el-radio-button value="qdrant">SQLite + Qdrant</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <p class="field-hint">{{ backendDescription }}</p>
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
            <p>{{ t('settings.memory.semanticDescription') }}</p>
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
            <p>{{ t('settings.memory.qdrantDescription') }}</p>
          </div>
        </div>
        <div class="form-grid">
          <el-form-item :label="t('settings.memory.qdrantUrl')">
            <el-input :model-value="modelValue.qdrant_url" @change="emitField('qdrant_url', $event)" />
          </el-form-item>
          <el-form-item :label="t('settings.memory.qdrantApiKey')">
            <el-input :model-value="modelValue.qdrant_api_key" type="password" show-password @change="emitField('qdrant_api_key', $event)" />
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
import { computed } from 'vue'
import { Connection, Refresh } from '@element-plus/icons-vue'

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
  defaultEmbeddingModel?: string
  defaultQdrantDockerImage?: string
}>()

const backendLabel = computed(() => ({
  sqlite: 'SQLite',
  inmemory: 'In-memory',
  qdrant: 'SQLite + Qdrant',
}[props.modelValue.backend] || props.modelValue.backend))

const backendDescription = computed(() => ({
  sqlite: t('settings.memory.backendSqliteDescription'),
  inmemory: t('settings.memory.backendMemoryDescription'),
  qdrant: t('settings.memory.backendQdrantDescription'),
}[props.modelValue.backend] || ''))

const emit = defineEmits<{
  'update-field': [field: keyof MemorySettings, value: MemorySettingValue]
  'change-backend': [backend: string]
  'discover-local': []
  rebuild: []
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

.block-heading h4,
.block-heading p,
.field-hint {
  margin: 0;
}

.block-heading h4 {
  color: var(--yui-text);
  font-size: 14px;
  font-weight: 700;
}

.block-heading p,
.field-hint {
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.55;
}

.field-hint {
  margin: -8px 0 14px;
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
