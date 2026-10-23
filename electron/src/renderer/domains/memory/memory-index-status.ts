import type { MemoryIndexStatus } from '@/api/clients/memory-client'
import { t } from '@/i18n'

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
    return { label: t('memoryView.indexLoading'), availabilityLabel: t('memoryView.indexPendingAvailability'), tone: 'info' }
  }

  const runtimeStatus = status.status.toLowerCase()
  const rebuildState = status.job?.state
  const indexDirty = status.metadata?.index_dirty === true
  const indexReady = status.healthy !== false
    && status.metadata?.index_healthy !== false
    && !indexDirty

  if (status.healthy === false) {
    return { label: t('memoryView.indexBackendError'), availabilityLabel: t('memoryView.indexAuthorityError'), tone: 'danger' }
  }
  if (rebuildState === 'failed' || rebuildState === 'interrupted' || runtimeStatus.includes('error') || runtimeStatus.includes('fail')) {
    return { label: t('memoryView.indexRebuildFailed'), availabilityLabel: t('memoryView.indexAuthorityAvailable'), tone: 'warning' }
  }
  if (rebuildState === 'cancelled') {
    return { label: t('memoryView.indexCancelled'), availabilityLabel: t('memoryView.indexAuthorityAvailable'), tone: 'info' }
  }
  if (runtimeStatus === 'indexing' || rebuildState === 'queued' || rebuildState === 'running' || rebuildState === 'cancelling') {
    return { label: t('memoryView.indexRebuilding'), availabilityLabel: t('memoryView.indexRebuildingAvailability'), tone: 'info' }
  }
  if (indexDirty) {
    return { label: t('memoryView.indexNeedsRebuild'), availabilityLabel: t('memoryView.indexNeedsRebuildAvailability'), tone: 'warning' }
  }
  if (!indexReady) {
    return { label: t('memoryView.indexUnavailable'), availabilityLabel: t('memoryView.indexAuthorityAvailable'), tone: 'warning' }
  }
  return { label: t('memoryView.indexAvailable'), availabilityLabel: t('memoryView.indexAvailableAvailability'), tone: 'success' }
}
