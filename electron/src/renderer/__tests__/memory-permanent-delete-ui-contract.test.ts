import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  resolve(process.cwd(), 'src/renderer/domains/memory/views/MemoryPanel.vue'),
  'utf8',
)

describe('memory permanent deletion UI contract', () => {
  it('presents deletion as irreversible and exposes no retired lifecycle controls', () => {
    expect(source).toContain('永久删除筛选结果')
    expect(source).toContain('这些记忆将从存储中永久删除。')
    expect(source).toContain('这条记忆将从存储中永久删除。')
    expect(source).toContain('confirmation: \'PERMANENT_DELETE\'')
    expect(source).not.toContain('忘记筛选结果')
    expect(source).not.toContain('停止召回并保留审计记录')
    expect(source).not.toContain('恢复筛选结果')
  })
})
