import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { buildPluginSandboxProcessArgs, resolveNodePermissionFlag } from '../plugin-sandbox'

describe('plugin sandbox process policy', () => {
  it('denies host capabilities and only allows reading the selected handler', () => {
    const handlerPath = path.resolve('plugins', 'weather', 'handler.mjs')
    const args = buildPluginSandboxProcessArgs(handlerPath)

    expect(args).toContain(resolveNodePermissionFlag())
    expect(args).toContain(`--allow-fs-read=${handlerPath}`)
    expect(args).not.toContain('--allow-fs-write=*')
    expect(args).not.toContain('--allow-net')
    expect(args).not.toContain('--allow-child-process')
    expect(args).not.toContain('--allow-worker')
  })

  it('uses the permission flag supported by the Node runtime', () => {
    expect(resolveNodePermissionFlag('20.20.2')).toBe('--experimental-permission')
    expect(resolveNodePermissionFlag('22.12.0')).toBe('--experimental-permission')
    expect(resolveNodePermissionFlag('22.13.0')).toBe('--permission')
    expect(resolveNodePermissionFlag('23.5.0')).toBe('--permission')
    expect(resolveNodePermissionFlag('24.0.0')).toBe('--permission')
  })
})
