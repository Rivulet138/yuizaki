import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const readPanel = (path: string) => readFileSync(
  resolve(process.cwd(), 'src/renderer/domains', path),
  'utf8',
)

describe('advanced panel action contracts', () => {
  it('keeps one trace refresh action for the shared trace snapshot', () => {
    const source = readPanel('system/views/AgentTracePanel.vue')
    expect(source.match(/@click="loadAgentTrace"/g)).toHaveLength(1)
  })

  it('keeps one global refresh action in the runtime checks panel', () => {
    const source = readPanel('deploy/views/DeployPanel.vue')
    expect(source.match(/@click="refreshAll"/g)).toHaveLength(1)
  })
})
