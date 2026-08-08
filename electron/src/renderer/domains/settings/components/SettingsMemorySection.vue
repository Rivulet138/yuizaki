<template>
  <el-card shadow="never">
    <template #header>
      <SettingsSectionHeader :title="t('settings.memory.title')">
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

    <el-form label-position="top" @submit.prevent>
      <el-form-item :label="t('settings.memory.backend')">
        <el-radio-group :model-value="modelValue.backend" @change="$emit('change-backend', String($event))">
          <el-radio-button value="sqlite">SQLite</el-radio-button>
          <el-radio-button value="inmemory">In-memory</el-radio-button>
          <el-radio-button value="qdrant">Qdrant</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item v-if="modelValue.backend === 'sqlite'" label="SQLite 存储文件">
        <el-input
          :model-value="modelValue.sqlite_path"
          placeholder="python/data/memory.db"
          @change="emitField('sqlite_path', $event)"
        />
      </el-form-item>
      <el-form-item :label="t('settings.memory.embedding')">
        <el-input
          :model-value="modelValue.embedding_model"
          :placeholder="defaultEmbeddingModel"
          @change="emitField('embedding_model', $event)"
        />
      </el-form-item>
      <el-form-item label="Learned reranker">
        <el-switch
          :model-value="modelValue.reranker_enabled"
          @change="emitField('reranker_enabled', $event)"
        />
      </el-form-item>

      <div v-if="modelValue.reranker_enabled" class="form-grid">
        <el-form-item label="Reranker model">
          <el-input :model-value="modelValue.reranker_model" @change="emitField('reranker_model', $event)" />
        </el-form-item>
        <el-form-item label="Reranker candidates">
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

      <template v-if="modelValue.backend === 'qdrant'">
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
      </template>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
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

defineProps<{
  modelValue: MemorySettings
  discoveryLoading: boolean
  rebuildLoading: boolean
  defaultEmbeddingModel?: string
  defaultQdrantDockerImage?: string
}>()

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

.form-grid.three {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

@media (max-width: 900px) {
  .form-grid,
  .form-grid.three {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
