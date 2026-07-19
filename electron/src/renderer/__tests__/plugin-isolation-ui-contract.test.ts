import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('plugin isolation UI contract', () => {
  it('renders the isolation mode reported by the runtime snapshot', () => {
    const panel = readFileSync(
      resolve(process.cwd(), 'src/renderer/domains/plugin/views/PluginManagementPanel.vue'),
      'utf8',
    )

    expect(panel).toContain('selectedPluginState?.executionIsolation')
    expect(panel).toContain('受限进程')
  })
})
