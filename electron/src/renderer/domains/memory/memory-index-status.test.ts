import { describe, expect, it, vi } from 'vitest'
vi.mock('@/i18n', () => ({ t: (key: string) => key }))
import { getMemoryIndexUiStatus } from './memory-index-status'
describe('memory index status contracts', () => {
  it.each([
    [{ index_ready: false }, 'memoryView.indexUnavailable'],
    [{ pending_index_count: 3 }, 'memoryView.indexNeedsRebuild'],
    [{ last_index_error: 'embedding offline' }, 'memoryView.indexRebuildFailed'],
    [{ index_ready: true, pending_index_count: 0 }, 'memoryView.indexAvailable'],
  ])('uses explicit backend readiness metadata %o', (metadata, label) => {
    expect(getMemoryIndexUiStatus({ status: 'ready', count: 1, healthy: true, metadata }, false).label).toBe(label)
  })
  it('keeps SQLite authority available when the derived index is unhealthy', () => {
    expect(getMemoryIndexUiStatus({ status: 'error', count: 1, healthy: false, metadata: { authority: 'sqlite' } }, false).availabilityLabel).toBe('memoryView.indexAuthorityAvailable')
  })
  it('does not infer index readiness from a generic ready status', () => {
    expect(getMemoryIndexUiStatus({ status: 'ready', count: 1 }, false).label).toBe('memoryView.indexUnavailable')
  })
  it('shows an active rebuild ahead of a previous index error', () => {
    expect(getMemoryIndexUiStatus({ status: 'indexing', count: 1, metadata: { last_index_error: 'previous failure' } }, false).label).toBe('memoryView.indexRebuilding')
  })
})
