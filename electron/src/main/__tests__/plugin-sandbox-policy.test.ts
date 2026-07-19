import { describe, expect, it } from 'vitest'
import { buildPluginSandboxProcessArgs } from '../plugin-sandbox'

describe('plugin sandbox process policy', () => {
  it('denies host capabilities and only allows reading the selected handler', () => {
    const handlerPath = 'C:\\plugins\\weather\\handler.mjs'
    const args = buildPluginSandboxProcessArgs(handlerPath)

    expect(args).toContain('--permission')
    expect(args).toContain(`--allow-fs-read=${handlerPath}`)
    expect(args).not.toContain('--allow-fs-write=*')
    expect(args).not.toContain('--allow-net')
    expect(args).not.toContain('--allow-child-process')
    expect(args).not.toContain('--allow-worker')
  })
})
