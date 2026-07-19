import { describe, expect, it } from 'vitest'

import { getMemoryIndexUiStatus } from '@/domains/memory/memory-index-status'

describe('memory index UI status', () => {
  it('distinguishes a healthy authority from an unavailable index', () => {
    expect(getMemoryIndexUiStatus({
      status: 'idle',
      count: 4,
      healthy: true,
      metadata: { index_healthy: false, index_dirty: false },
    }, false)).toEqual({
      label: '索引不可用',
      availabilityLabel: '权威库可用',
      tone: 'warning',
    })
  })

  it('shows index drift as requiring a rebuild', () => {
    expect(getMemoryIndexUiStatus({
      status: 'idle',
      count: 4,
      healthy: true,
      metadata: { index_healthy: false, index_dirty: true },
    }, false)).toEqual({
      label: '需重建',
      availabilityLabel: '索引需重建',
      tone: 'warning',
    })
  })

  it('keeps rebuilding distinct from a ready index', () => {
    expect(getMemoryIndexUiStatus({
      status: 'indexing',
      count: 4,
      healthy: true,
      metadata: { index_healthy: true, index_dirty: false },
    }, false)).toEqual({
      label: '重建中',
      availabilityLabel: '索引重建中',
      tone: 'info',
    })
  })

  it('reports a ready index only when both layers are healthy', () => {
    expect(getMemoryIndexUiStatus({
      status: 'idle',
      count: 4,
      healthy: true,
      metadata: { index_healthy: true, index_dirty: false },
    }, false)).toEqual({
      label: '可用',
      availabilityLabel: '索引可用',
      tone: 'success',
    })
  })
})
