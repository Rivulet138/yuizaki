import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  resolve(process.cwd(), 'src/renderer/domains/system/views/InfrastructurePanel.vue'),
  'utf8',
)

describe('infrastructure panel UI contract', () => {
  it('names resource actions after the Electron API they invoke', () => {
    expect(source).toContain('clearSessionCache()')
    expect(source).toContain('清理 HTTP 缓存')
    expect(source).not.toContain('清理运行缓存')
    expect(source).not.toContain('仅清理当前 Electron 会话的 HTTP 缓存')
  })

  it('presents backend diagnostics as functional snapshots', () => {
    expect(source).toContain('systemClient.systemStatus()')
    expect(source).toContain('systemClient.databaseStats()')
    expect(source).toContain('接口快照')
    expect(source).toContain('读取快照')
    expect(source).not.toContain('后端接口核对')
    expect(source).not.toContain('核对接口')
  })
})
