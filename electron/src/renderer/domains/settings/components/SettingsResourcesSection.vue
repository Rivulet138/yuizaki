<template>
  <div class="resource-stack">
    <el-alert
      v-if="resourceMessage"
      :title="resourceMessage"
      :type="resourceMessageType"
      show-icon
      :closable="false"
    />

    <div class="button-row">
      <el-button plain :loading="resourceLoading || storageLoading" @click="emit('refresh')">{{ t('settings.resource.refresh') }}</el-button>
      <el-button
        v-if="cancellableResourceIds.length > 0"
        type="danger"
        plain
        :icon="CircleClose"
        :loading="resourceCancelLoading"
        @click="emit('cancel-downloads')"
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
        <div class="resource-progress-meta">
          <span v-if="progress.message">{{ progress.message }}</span>
          <span v-if="progress.bytesDownloaded !== null" class="resource-progress-bytes">
            {{ formatStorageBytes(progress.bytesDownloaded) }}<template v-if="progress.bytesTotal !== null"> / {{ formatStorageBytes(progress.bytesTotal) }}</template>
          </span>
        </div>
      </div>
    </div>

    <div v-if="resourceDownloadOptions.length" class="resource-download-bar">
      <el-checkbox-group
        :model-value="selectedResourceIds"
        class="resource-download-options"
        @update:model-value="updateSelectedResourceIds"
      >
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
        @click="emit('download-selected')"
      >下载选中项</el-button>
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
            @click="emit('cleanup-all')"
          >{{ t('settings.storage.cleanAll') }}</el-button>
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
              @click="requestStorageCleanup(scope.row.id)"
            >{{ t('settings.storage.permanentClean') }}</el-button>
            <el-button
              v-else-if="scope.row?.action === 'compact'"
              plain
              size="small"
              :icon="Refresh"
              :loading="storageActionKey === scope.row.id"
              @click="requestStorageCleanup(scope.row.id)"
            >{{ t('settings.storage.compact') }}</el-button>
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
          <div><strong>{{ t('settings.resource.live2dRoot') }}</strong><code class="resource-path">{{ resourceView.modelRoots.live2d }}</code></div>
          <div><strong>{{ t('settings.resource.vrmRoot') }}</strong><code class="resource-path">{{ resourceView.modelRoots.vrm }}</code></div>
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
          <div><strong>{{ t('settings.resource.model') }}</strong><code class="resource-path">{{ resourceView.sherpaOnline.modelPath }}</code></div>
          <div><strong>Sherpa Tokens</strong><code class="resource-path">{{ resourceView.sherpaOnline.tokensPath }}</code></div>
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
          <el-button type="primary" plain :loading="resourceActionLoading('sherpa-online-download')" @click="emit('prepare-resource', 'sherpa_online')">
            {{ t('settings.resource.downloadSherpa') }} (Streaming)
          </el-button>
          <el-button
            v-if="resourceView.sherpaOnline.state !== 'missing'"
            type="danger"
            plain
            :icon="Delete"
            :loading="resourceActionLoading('remove-sherpa_online')"
            @click="emit('remove-resource', 'sherpa_online', '流式语音识别', resourceView.sherpaOnline.metadata)"
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
          <div><strong>{{ t('settings.resource.checkpoint') }}</strong><code class="resource-path">{{ resourceView.soulx.checkpointPath || resourceView.soulx.checkpointCandidates[0] }}</code></div>
          <div><strong>{{ t('settings.resource.preprocessDir') }}</strong><code class="resource-path">{{ resourceView.soulx.preprocessDir }}</code></div>
          <div><strong>{{ t('settings.resource.referenceDir') }}</strong><code class="resource-path">{{ resourceView.soulx.referenceDir }}</code></div>
          <div>
            <strong>参考音频</strong>
            <el-tag :type="resourceView.soulx.hasReferenceAudio ? 'success' : 'info'">{{ resourceView.soulx.hasReferenceAudio ? '已导入' : '未导入' }}</el-tag>
          </div>
        </div>
        <ul v-if="resourceView.soulx.details.length" class="resource-list">
          <li v-for="detail in resourceView.soulx.details" :key="detail">{{ detail }}</li>
        </ul>
        <div class="button-row resource-actions">
          <el-button type="primary" plain :loading="resourceActionLoading('soulx-download')" @click="emit('prepare-resource', 'soulx')">{{ t('settings.resource.downloadSoulx') }}</el-button>
          <el-button plain :loading="resourceActionLoading('soulx-reference')" @click="emit('import-soulx-reference')">{{ t('settings.resource.importReference') }}</el-button>
          <el-button
            v-if="resourceView.soulx.state !== 'missing'"
            type="danger"
            plain
            :icon="Delete"
            :loading="resourceActionLoading('remove-soulx')"
            @click="emit('remove-resource', 'soulx', 'SoulX 变声', resourceView.soulx.metadata)"
          >永久卸载</el-button>
        </div>
      </el-card>

      <el-card class="resource-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span>GPT-SoVITS（本地导入）</span>
            <el-tag :type="resourceTagType(resourceView.gptSovits.state)">{{ resourceView.gptSovits.message }}</el-tag>
          </div>
        </template>
        <div class="resource-details">
          <div><strong>模型目录</strong><code class="resource-path">{{ resourceView.gptSovits.modelDir }}</code></div>
          <div><strong>体积</strong><el-tag size="small" type="info">约 4.94 GiB · 不自动下载</el-tag></div>
        </div>
        <div class="button-row resource-actions">
          <el-button type="primary" plain :loading="resourceActionLoading('gpt-sovits-check')" @click="emit('prepare-resource', 'gpt_sovits')">检查本地资源</el-button>
          <el-button
            v-if="resourceView.gptSovits.state !== 'missing'"
            type="danger"
            plain
            :icon="Delete"
            :loading="resourceActionLoading('remove-gpt_sovits')"
            @click="emit('remove-resource', 'gpt_sovits', 'GPT-SoVITS', resourceView.gptSovits.metadata)"
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
          <div><strong>{{ t('settings.resource.model') }}</strong><code class="resource-path">{{ resourceView.sherpa.modelPath }}</code></div>
          <div><strong>Sherpa Tokens</strong><code class="resource-path">{{ resourceView.sherpa.tokensPath }}</code></div>
        </div>
        <ul v-if="resourceView.sherpa.details.length" class="resource-list">
          <li v-for="detail in resourceView.sherpa.details" :key="detail">{{ detail }}</li>
        </ul>
        <div class="button-row resource-actions">
          <el-button type="primary" plain :loading="resourceActionLoading('sherpa-download')" @click="emit('prepare-resource', 'sherpa')">{{ t('settings.resource.downloadSherpa') }}</el-button>
          <el-button
            v-if="resourceView.sherpa.state !== 'missing'"
            type="danger"
            plain
            :icon="Delete"
            :loading="resourceActionLoading('remove-sherpa')"
            @click="emit('remove-resource', 'sherpa', '离线语音识别', resourceView.sherpa.metadata)"
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
          <div><strong>{{ t('settings.resource.model') }}</strong><code class="resource-path">{{ resourceView.embedding.modelName }}</code></div>
          <div><strong>{{ t('settings.resource.snapshot') }}</strong><code class="resource-path">{{ resourceView.embedding.cachePath || resourceView.embedding.cacheRoot }}</code></div>
        </div>
        <ul v-if="resourceView.embedding.details.length" class="resource-list">
          <li v-for="detail in resourceView.embedding.details" :key="detail">{{ detail }}</li>
        </ul>
        <div class="button-row resource-actions">
          <el-button type="primary" plain :loading="resourceActionLoading('embedding-prefetch')" @click="emit('prepare-resource', 'embedding')">{{ t('settings.resource.prefetchEmbedding') }}</el-button>
          <el-button
            v-if="resourceView.embedding.state !== 'missing'"
            type="danger"
            plain
            :icon="Delete"
            :loading="resourceActionLoading('remove-embedding')"
            @click="emit('remove-resource', 'embedding', '长期记忆嵌入', resourceView.embedding.metadata)"
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
          <div><strong>{{ t('settings.resource.character') }}</strong><code class="resource-path">{{ resourceView.tts.character }}</code></div>
          <div><strong>{{ t('settings.resource.cacheDir') }}</strong><code class="resource-path">{{ resourceView.tts.cacheDir }}</code></div>
          <div><strong>{{ t('settings.resource.modelDir') }}</strong><code class="resource-path">{{ resourceView.tts.modelDir }}</code></div>
        </div>
        <ul v-if="resourceView.tts.details.length" class="resource-list">
          <li v-for="detail in resourceView.tts.details" :key="detail">{{ detail }}</li>
        </ul>
        <div class="button-row resource-actions">
          <el-button type="primary" plain :loading="resourceActionLoading('tts-prefetch')" @click="emit('prepare-resource', 'tts')">{{ t('settings.resource.prefetchTts') }}</el-button>
          <el-button
            v-if="resourceView.tts.state !== 'missing'"
            type="danger"
            plain
            :icon="Delete"
            :loading="resourceActionLoading('remove-tts')"
            @click="emit('remove-resource', 'tts', 'Genie TTS', resourceView.tts.metadata)"
          >永久卸载</el-button>
        </div>
      </el-card>
    </div>

    <el-empty v-else :description="t('settings.resource.noStatus')" />
  </div>
</template>

<script setup lang="ts">
import { CircleClose, Delete, Download, Refresh } from '@element-plus/icons-vue'
import { t } from '@/i18n'
import type {
  ManagedModelResourceId,
  ManagedResourceMetadata,
  ModelResourceStatusPayload,
  ResumableResourceDownload,
  ResourceDownloadProgress,
  ResourceProgressPhase,
  StorageCategoryId,
  StorageStatusPayload,
} from '@/../shared/resource-manager'

type AlertType = 'success' | 'warning' | 'info' | 'error'
type StorageCleanupTarget = Exclude<StorageCategoryId, 'visual_frames'>

interface ResourceDownloadOption {
  id: ManagedModelResourceId
  label: string
  ready: boolean
  version: string
  license: string
  downloadBytes: number
  resumable: ResumableResourceDownload | null
}

const props = defineProps<{
  resourceMessage: string
  resourceMessageType: AlertType
  resourceLoading: boolean
  storageLoading: boolean
  cancellableResourceIds: ManagedModelResourceId[]
  resourceCancelLoading: boolean
  activeDownloadProgress: ResourceDownloadProgress[]
  resourceView: ModelResourceStatusPayload | null
  selectedResourceIds: ManagedModelResourceId[]
  resourceDownloadOptions: ResourceDownloadOption[]
  storageStatus: StorageStatusPayload | null
  resourceActionKey: string
  storageActionKey: string
}>()

const emit = defineEmits<{
  refresh: []
  'cancel-downloads': []
  'update:selectedResourceIds': [ids: ManagedModelResourceId[]]
  'download-selected': []
  'prepare-resource': [id: ManagedModelResourceId]
  'import-soulx-reference': []
  'remove-resource': [id: ManagedModelResourceId, label: string, metadata: ManagedResourceMetadata]
  'cleanup-storage': [targets: StorageCleanupTarget[]]
  'cleanup-all': []
}>()

const resourceActionLoading = (key: string) => props.resourceActionKey === key
const resourceTagType = (state: 'missing' | 'partial' | 'ready') => state === 'ready' ? 'success' : state === 'partial' ? 'warning' : 'danger'

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
  gpt_sovits: 'GPT-SoVITS',
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
const resourceProgressLabel = (id: ManagedModelResourceId) => resourceProgressLabels[id]
const resourceProgressPhaseLabel = (phase: ResourceProgressPhase) => resourceProgressPhaseLabels[phase]
const storageCategoryLabel = (id: StorageCategoryId) => t(`settings.storage.category.${id}`)

const updateSelectedResourceIds = (value: unknown) => {
  if (!Array.isArray(value)) return
  const allowed = new Set<ManagedModelResourceId>(['soulx', 'gpt_sovits', 'sherpa', 'sherpa_online', 'embedding', 'tts'])
  emit('update:selectedResourceIds', value.filter((id): id is ManagedModelResourceId => allowed.has(id as ManagedModelResourceId)))
}

const requestStorageCleanup = (id: StorageCategoryId) => {
  if (id === 'visual_frames') return
  emit('cleanup-storage', [id])
}
</script>

<style scoped src="./SettingsResourcesSection.css"></style>
