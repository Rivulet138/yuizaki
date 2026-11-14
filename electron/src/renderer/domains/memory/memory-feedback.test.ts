import { describe, expect, it, vi } from 'vitest'
vi.mock('@/i18n', () => ({ currentLocale: { value: 'zh-CN' } }))
import { memoryDeletionResultText, memoryIndexCleanupStatus } from './memory-feedback'

describe('memory deletion cleanup feedback', () => {
  it.each([
    ['complete', 'deleted', '索引清理已完成'],
    ['pending', 'authority_deleted', '索引清理待恢复'],
    ['unknown', 'authority_deleted', '索引清理尚未确认'],
  ])('explains %s without losing authority deletion', (cleanup, status, detail) => {
    const response = { status, index_cleanup_status: cleanup }
    expect(memoryIndexCleanupStatus(response)).toBe(cleanup)
    const message = memoryDeletionResultText(response, '权威记录已删除')
    expect(message).toContain('权威记录已删除')
    expect(message).toContain(detail)
    if (cleanup !== 'complete') expect(message).toContain('无需重复删除')
  })
  it('does not treat a legacy status or recall exclusion as cleanup confirmation', () => {
    for (const response of [{ status: 'deleted' }, { status: 'purged' }, { index_status: 'excluded' }, { index_cleanup_status: 'excluded' }, null]) {
      expect(memoryIndexCleanupStatus(response)).toBe('unknown')
      expect(memoryDeletionResultText(response, '权威记录已删除')).not.toContain('索引清理已完成')
    }
  })
})
