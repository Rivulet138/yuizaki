import type { MemoryIndexStatus } from '@/api/clients/memory-client'

export type MemoryIndexStatusTone = 'success' | 'warning' | 'danger' | 'info'

export interface MemoryIndexUiStatus {
  label: string
  availabilityLabel: string
  tone: MemoryIndexStatusTone
}

export const getMemoryIndexUiStatus = (
  status: MemoryIndexStatus | null,
  loading: boolean,
): MemoryIndexUiStatus => {
  if (!status || loading) {
    return { label: '加载中', availabilityLabel: '状态待载入', tone: 'info' }
  }

  const runtimeStatus = status.status.toLowerCase()
  const rebuildState = status.job?.state
  const indexDirty = status.metadata?.index_dirty === true
  const indexReady = status.healthy !== false
    && status.metadata?.index_healthy !== false
    && !indexDirty

  if (status.healthy === false) {
    return { label: '后端异常', availabilityLabel: '权威库异常', tone: 'danger' }
  }
  if (rebuildState === 'failed' || rebuildState === 'interrupted' || runtimeStatus.includes('error') || runtimeStatus.includes('fail')) {
    return { label: '重建失败', availabilityLabel: '权威库可用', tone: 'warning' }
  }
  if (rebuildState === 'cancelled') {
    return { label: '已取消', availabilityLabel: '权威库可用', tone: 'info' }
  }
  if (runtimeStatus === 'indexing' || rebuildState === 'queued' || rebuildState === 'running' || rebuildState === 'cancelling') {
    return { label: '重建中', availabilityLabel: '索引重建中', tone: 'info' }
  }
  if (indexDirty) {
    return { label: '需重建', availabilityLabel: '索引需重建', tone: 'warning' }
  }
  if (!indexReady) {
    return { label: '索引不可用', availabilityLabel: '权威库可用', tone: 'warning' }
  }
  return { label: '可用', availabilityLabel: '索引可用', tone: 'success' }
}
