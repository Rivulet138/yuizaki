<template>
  <section class="storage-status" aria-live="polite">
    <strong>{{ memoryText('当前记忆范围', 'Memory scope') }}: {{ scope }} · {{ scope === 'global' ? memoryText('全局独立范围', 'Separate global scope') : workspaceId }}<template v-if="scope === 'session'"> · {{ sessionId }}</template></strong>
    <p>{{ memoryText('权威存储', 'Authority') }}: {{ metadata.authority || memoryText('未报告', 'Not reported') }} · {{ memoryText('索引', 'Index') }}: {{ uiStatus.label }} · {{ uiStatus.availabilityLabel }}</p>
    <p>{{ memoryText('存储修订', 'Authority revision') }}: {{ metadata.authority_revision ?? memoryText('未提供', 'Not reported') }} · {{ memoryText('索引代次', 'Index generation') }}: {{ metadata.index_generation ?? memoryText('尚未激活', 'Not activated') }} · {{ memoryText('索引快照修订', 'Index snapshot revision') }}: {{ metadata.index_snapshot_revision ?? memoryText('未提供或尚未激活', 'Not reported or not activated') }}</p>
    <p v-if="metadata.pending_index_count !== undefined">{{ memoryText('待索引记录', 'Pending indexing') }}: {{ metadata.pending_index_count }}</p>
    <p v-if="metadata.last_index_error" role="alert">{{ metadata.last_index_error }}</p>
    <p v-if="overview?.recall_policy">{{ memoryText('服务端召回策略', 'Server recall policy') }}: {{ overview.recall_policy.scope }} · {{ memoryText('继承范围', 'Inherited scopes') }}: {{ overview.recall_policy.inherited_scopes.join(', ') || '∅' }}</p>
    <p v-if="overview?.by_index_status">{{ memoryText('范围内索引分布', 'Index states in this scope') }}: <span v-for="(count, state) in overview.by_index_status" :key="state">{{ state }} {{ count }} · </span></p>
    <details v-if="overview?.integrity?.orphan_session_ids.length">
      <summary>{{ memoryText('孤立会话诊断：需要显式分配，不会自动归属', 'Orphan sessions: explicit assignment required; no automatic reassignment') }} ({{ overview.integrity.orphan_session_ids.length }})</summary>
      <p>{{ overview.integrity.orphan_resolution }}</p><code>{{ overview.integrity.orphan_session_ids.join(' · ') }}</code>
    </details>
    <p v-if="overview?.deletion_scope">{{ memoryText('删除影响', 'Deletion effects') }}: <span v-for="(effect, area) in overview.deletion_scope" :key="area">{{ area }}={{ effect }} · </span></p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MemoryIndexStatus } from '@/api/clients/memory-client'
import type { MemoryOverviewSnapshot } from '../composables/useMemoryDomain'
import { memoryText } from '../memory-feedback'
import { getMemoryIndexUiStatus } from '../memory-index-status'
const props = defineProps<{ status: MemoryIndexStatus | null; overview: MemoryOverviewSnapshot | null; scope: string; workspaceId: string; sessionId?: string }>()
const metadata = computed(() => props.status?.metadata ?? props.overview?.index_health?.metadata ?? {})
const uiStatus = computed(() => getMemoryIndexUiStatus(props.status, false))
</script>

<style scoped>
.storage-status { padding: 12px 14px; border: 1px solid var(--yui-border); border-radius: 12px; color: var(--yui-muted); font-size: 12px; overflow-wrap: anywhere; }
.storage-status strong { color: var(--yui-text); }
.storage-status p { margin: 6px 0 0; }
.storage-status details { margin-top: 8px; }
</style>
