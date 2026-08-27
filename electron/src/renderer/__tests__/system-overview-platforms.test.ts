import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  resolve(process.cwd(), 'src/renderer/domains/system/views/OverviewPanel.vue'),
  'utf8',
)

describe('system overview platform matrix', () => {
  it('renders backend statuses without claiming platform parity', () => {
    expect(source).toContain('平台能力')
    expect(source).toContain('systemClient.platforms()')
    expect(source).toContain("available: '可用'")
    expect(source).toContain("needs_config: '需配置'")
    expect(source).toContain("experimental: '实验性'")
    expect(source).toContain("planned: '规划中'")
    expect(source).toContain("unsupported: '不支持'")
  })

  it('keeps the capability table readable in compact windows', () => {
    expect(source).toContain('@media (max-width: 760px)')
    expect(source).toContain('.platform-table tbody tr')
    expect(source).toContain('display: block')
    expect(source).toContain('overflow-wrap: anywhere')
  })
})
