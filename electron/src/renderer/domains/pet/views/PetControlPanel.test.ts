import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

describe('pet renderer type contracts', () => {
  it('accepts control values, narrowed operation IDs, and runtime placement/cancellation', () => {
    const root = fileURLToPath(new URL('../../../../..', import.meta.url))
    const result = spawnSync(process.execPath, [
      'node_modules/vue-tsc/bin/vue-tsc.js',
      '--noEmit', '-p', 'tsconfig.renderer.json', '--pretty', 'false',
    ], { cwd: root, encoding: 'utf8', timeout: 90_000, maxBuffer: 32 * 1024 * 1024 })
    const output = `${result.stdout ?? ''}${result.stderr ?? ''}`.replaceAll('\\', '/')

    expect(result.error, output).toBeUndefined()
    expect(result.signal, output).toBeNull()
    expect([0, 1, 2], output).toContain(result.status)
    if (result.status !== 0) expect(output).toMatch(/\(\d+,\d+\): error TS\d+:/)

    const ownedErrors = output.split(/\r?\n/).filter(line =>
      /(?:^|\/)(?:PetControlPanel\.vue|pet-renderer\.ts|live2d-runtime-adapter\.ts)\(\d+,\d+\): error TS\d+:/.test(line),
    )
    expect(ownedErrors).toEqual([])
  }, 100_000)
})
