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

  it('keeps a rebuild failure distinct from an authority failure', () => {
    expect(getMemoryIndexUiStatus({
      status: 'error',
      count: 4,
      healthy: true,
      metadata: { index_healthy: false, index_dirty: true },
      job: {
        job_id: 'job-1', state: 'failed', phase: 'failed', processed_count: 2, total_count: 4,
        started_at: '2026-08-27T00:00:00Z', updated_at: '2026-08-27T00:00:01Z',
        last_error: 'embedding unavailable', recoverable: true,
      },
    }, false)).toEqual({
      label: '重建失败',
      availabilityLabel: '权威库可用',
      tone: 'warning',
    })
  })

  it('shows a cancelled rebuild without implying memory loss', () => {
    expect(getMemoryIndexUiStatus({
      status: 'idle',
      count: 4,
      healthy: true,
      metadata: { index_healthy: false, index_dirty: true },
      job: {
        job_id: 'job-2', state: 'cancelled', phase: 'cancelled', processed_count: 2, total_count: 4,
        started_at: '2026-08-27T00:00:00Z', updated_at: '2026-08-27T00:00:01Z',
        recoverable: true,
      },
    }, false)).toEqual({
      label: '已取消',
      availabilityLabel: '权威库可用',
      tone: 'info',
    })
  })

  it('surfaces an unavailable index as a backend failure instead of loading forever', () => {
    expect(getMemoryIndexUiStatus({
      status: 'error',
      count: 4,
      healthy: false,
      message: 'control service unavailable',
      metadata: { index_healthy: false, degraded: true },
    }, false)).toEqual({
      label: '后端异常',
      availabilityLabel: '权威库异常',
      tone: 'danger',
    })
  })
})
