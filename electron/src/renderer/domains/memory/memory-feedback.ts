import type { MemoryIndexCleanupStatus } from '@/api/clients/memory-client'
import { currentLocale } from '@/i18n'

export const memoryText = (zh: string, en: string) => currentLocale.value === 'zh-CN' ? zh : en
export const memoryIndexLabel = (status?: string) => ({
  indexed: memoryText('已索引；是否召回仍取决于范围与筛选', 'Indexed; recall still depends on scope and filters'),
  pending: memoryText('权威数据已保存，索引待处理', 'Authority saved; indexing pending'),
  failed: memoryText('权威数据已保存，索引失败，可重建', 'Authority saved; indexing failed, rebuild available'),
  excluded: memoryText('已保存；当前状态不纳入索引', 'Saved; current state excluded from index'),
}[status || ''] || memoryText('索引状态未提供', 'Index state not reported'))
export const memoryDeletionNote = () => memoryText(
  '删除仅影响选定的权威记录和派生索引；聊天历史、会话摘要和已有备份保持不变，不代表这些上下文已经遗忘。',
  'Deletion affects the selected authority records and derived indexes. Chat history, summaries and existing backups remain unchanged and may retain context.',
)

export const memoryIndexCleanupStatus = (result: unknown): MemoryIndexCleanupStatus => {
  const status = result && typeof result === 'object' ? (result as { index_cleanup_status?: unknown }).index_cleanup_status : undefined
  return status === 'complete' || status === 'pending' ? status : 'unknown'
}
export const memoryDeletionResultText = (result: unknown, authorityMessage: string) => {
  const cleanup = memoryIndexCleanupStatus(result)
  if (cleanup === 'complete') return authorityMessage + ' · ' + memoryText('索引清理已完成', 'Index cleanup complete')
  return authorityMessage + ' · ' + (cleanup === 'pending'
    ? memoryText('权威记录已删除；远端索引清理待恢复。请核对索引状态，无需重复删除。', 'Authority records deleted; remote index cleanup is pending recovery. Check index status without repeating deletion.')
    : memoryText('权威记录已删除；索引清理尚未确认。请核对索引状态，无需重复删除。', 'Authority records deleted; index cleanup is unconfirmed. Check index status without repeating deletion.'))
}
