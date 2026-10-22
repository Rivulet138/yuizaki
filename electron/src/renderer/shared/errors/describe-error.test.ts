import { describe, expect, it } from 'vitest'

import { describeError, describeFailure, explainError } from './describe-error'

const httpError = (patch: Record<string, unknown>) => Object.assign(new Error(''), patch)

describe('explainError', () => {
  it('translates a known machine code and keeps it for support', () => {
    const explanation = explainError(httpError({ code: 'dsh_empty_output' }))
    expect(explanation.title).toContain('DSH')
    expect(explanation.action).toContain('DEEPSEEK_API_KEY')
    expect(explanation.code).toBe('dsh_empty_output')
  })

  it('recognises a code delivered as the message itself', () => {
    const explanation = explainError(httpError({ message: 'qq_bridge_not_installed' }))
    expect(explanation.title).toContain('尚未安装')
    expect(explanation.code).toBe('qq_bridge_not_installed')
  })

  it('recognises a code nested in the payload error field', () => {
    const nested = explainError(httpError({ payload: { error: 'rate_limited' } }))
    expect(nested.code).toBe('rate_limited')
    expect(nested.title).toContain('频率')
  })

  it('falls back to the HTTP status when the code is unknown', () => {
    const explanation = explainError(httpError({ status: 401, code: 'something_new', message: 'Token not provided' }))
    expect(explanation.title).toContain('身份验证')
    expect(explanation.action).toContain('Token not provided')
    expect(explanation.code).toBe('something_new')
    expect(explanation.status).toBe(401)
  })

  it('keeps a readable backend sentence instead of showing a code', () => {
    const explanation = explainError(httpError({ status: 500, message: '数据库暂时不可用' }))
    expect(explanation.title).toContain('数据库暂时不可用')
  })

  it('never surfaces a bare http_ wrapper or an empty sentence', () => {
    const explanation = explainError(httpError({ status: 400, message: 'http_400' }))
    expect(explanation.title).not.toMatch(/http_400/)
    expect(explanation.title.length).toBeGreaterThan(1)
  })

  it('handles null, strings and unknown objects', () => {
    expect(explainError(null).title).toContain('操作失败')
    expect(explainError('随便一段话').title).toBe('操作失败')
    expect(explainError(httpError({ requestId: 'req-1' })).title).toContain('操作失败')
  })

  it('carries requestId through for support', () => {
    const explanation = explainError(httpError({ status: 502, requestId: 'req-42' }))
    expect(explanation.requestId).toBe('req-42')
  })
})

describe('describeError', () => {
  it('joins title and action into one actionable sentence', () => {
    const text = describeError(httpError({ code: 'qq_bridge_hash_mismatch' }))
    expect(text).toContain('校验失败')
    expect(text).toContain('sha256')
    expect(text).toContain('qq_bridge_hash_mismatch')
  })

  it('does not repeat the code when the sentence already contains it', () => {
    const text = describeError(httpError({ status: 409, code: 'connector_disabled' }))
    expect(text.split('connector_disabled').length - 1).toBe(1)
  })

  it('always returns a non-empty string', () => {
    expect(describeError(undefined)).not.toHaveLength(0)
    expect(describeError(new Error(''))).not.toHaveLength(0)
  })
})

describe('describeFailure', () => {
  it('prefers the shared explanation when a known code arrives', () => {
    const text = describeFailure(httpError({ code: 'llm_key_missing' }), '保存失败')
    expect(text).toContain('API Key')
    expect(text).not.toContain('保存失败')
  })

  it('prefers the shared explanation when only an HTTP status arrives', () => {
    const text = describeFailure(httpError({ status: 503, message: 'upstream down' }), '保存失败')
    expect(text).toContain('服务暂时不可用')
    expect(text).toContain('upstream down')
  })

  it('keeps the caller context for an unidentifiable failure', () => {
    expect(describeFailure(new Error('TypeError: x is not a function'), '批量删除失败')).toBe('批量删除失败')
  })

  it('keeps the caller context for an unknown code', () => {
    expect(describeFailure(httpError({ code: 'brand_new_code' }), '刷新失败')).toBe('刷新失败')
  })

  it('never returns an empty string when context is missing', () => {
    expect(describeFailure(new Error('boom'))).not.toHaveLength(0)
    expect(describeFailure(undefined, '   ')).not.toHaveLength(0)
  })

  it('does not leak a raw transport message for unidentified failures', () => {
    const text = describeFailure(httpError({ message: 'Network Error' }), '连接失败')
    expect(text).toBe('连接失败')
  })
})
