import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

describe('OnboardingModelSetup template types', () => {
  it('type-checks every draft field binding with vue-tsc', () => {
    const root = fileURLToPath(new URL('../../../../..', import.meta.url))
    const result = spawnSync(process.execPath, [
      'node_modules/vue-tsc/bin/vue-tsc.js',
      '--noEmit',
      '-p', 'tsconfig.renderer.json',
      '--pretty', 'false',
    ], {
      cwd: root,
      encoding: 'utf8',
      timeout: 90_000,
      maxBuffer: 32 * 1024 * 1024,
    })
    const output = `${result.stdout ?? ''}${result.stderr ?? ''}`.replaceAll('\\', '/')

    expect(result.error, output).toBeUndefined()
    expect(result.signal, output).toBeNull()
    expect([0, 1, 2], output).toContain(result.status)
    if (result.status !== 0) expect(output).toMatch(/\(\d+,\d+\): error TS\d+:/)

    // Unrelated renderer errors are owned by the existing baseline gate.
    const componentErrors = output.split(/\r?\n/).filter(line =>
      /(?:^|\/)OnboardingModelSetup\.vue\(\d+,\d+\): error TS\d+:/.test(line),
    )
    expect(componentErrors).toEqual([])
  }, 100_000)
})
