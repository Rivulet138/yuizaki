import { redactDiagnosticText } from '@/app/runtime/companionDiagnosticExport'

export type ToolActionStatus = 'executing' | 'completed' | 'verified' | 'failed' | 'unknown_effect' | 'cancelled'

const marker = (value: unknown): string => typeof value === 'string'
  ? value.trim().toLowerCase().replace(/[\s-]+/g, '_')
  : ''

export const projectToolActionStatus = (
  status?: string | null,
  verificationStatus?: unknown,
): ToolActionStatus => {
  const state = marker(status)
  const verification = marker(verificationStatus)
  if (state === 'unknown_effect') return 'unknown_effect'
  if (['failed', 'error'].includes(state)) return 'failed'
  if (['cancelled', 'interrupted'].includes(state)) return 'cancelled'
  if (verification === 'verified') return 'verified'
  if (['ok', 'completed', 'success', 'succeeded'].includes(state)) return 'completed'
  return 'executing'
}

export const toolActionStatusLabel = (status?: string | null): string => {
  const state = marker(status)
  const labels: Record<ToolActionStatus, string> = {
    executing: '执行中',
    completed: '已完成（未验证）',
    verified: '已验证',
    failed: '失败',
    unknown_effect: '结果未知',
    cancelled: '已停止',
  }
  return labels[state as ToolActionStatus] ?? labels.executing
}

export const toolEvidenceFromRecord = (record: Record<string, unknown>): string[] => {
  return [record.evidence, record.verificationEvidence, record.verification_evidence, record.postconditionEvidence, record.postcondition_evidence]
    .flatMap(value => Array.isArray(value) ? value : [value])
    .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
    .map(value => redactDiagnosticText(value.trim().replace(/\s+/g, ' ').slice(0, 240)))
    .slice(0, 3)
}

