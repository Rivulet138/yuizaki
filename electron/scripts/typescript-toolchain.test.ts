import fs from 'node:fs'
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const electronRoot = fileURLToPath(new URL('../', import.meta.url))
const requireFromElectron = createRequire(new URL('../package.json', import.meta.url))
const manifest = JSON.parse(fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8'))
const nativeEntry = fileURLToPath(new URL('../node_modules/typescript-native/bin/tsc', import.meta.url))
const nativeCommand = 'node node_modules/typescript-native/bin/tsc'

describe('TypeScript toolchain separation', () => {
  it('keeps the legacy compiler API separate from the native compiler alias', () => {
    expect(manifest.devDependencies.typescript).toBe('^6.0.3')
    expect(manifest.devDependencies['typescript-native']).toBe('npm:typescript@^7.0.2')
  })

  it.each([
    ['dev:main', `${nativeCommand} -p tsconfig.json -w`],
    ['build:electron', `${nativeCommand} -p tsconfig.json`],
    ['type-check', `${nativeCommand} --noEmit -p tsconfig.json && npm run type-check:renderer`],
  ])('uses the explicit native compiler entry for %s', (name, command) => {
    expect(manifest.scripts[name]).toBe(command)
  })

  it('does not rely on an npm tsc or tsserver bin shim in any package script', () => {
    for (const command of Object.values(manifest.scripts)) {
      expect(command).not.toMatch(/(?:^|[\s;&|"'])(?:tsc|tsserver)(?:\.(?:cmd|exe))?(?=$|[\s;&|"'])/)
    }
  })

  it('preserves the renderer checker and legacy API resolution for Vue and ESLint', () => {
    expect(manifest.scripts['type-check:renderer']).toBe('node scripts/check-renderer-types.mjs')
    for (const consumer of ['vue-tsc', 'typescript-eslint']) {
      const requireFromConsumer = createRequire(requireFromElectron.resolve(consumer))
      expect(requireFromConsumer.resolve('typescript')).toBe(requireFromElectron.resolve('typescript'))
      const compiler = requireFromConsumer('typescript')
      expect(compiler.version).toMatch(/^6\.0\./)
      expect(typeof compiler.createProgram).toBe('function')
    }
  })

  it('runs TS7 and parses the main-process configuration', () => {
    const version = spawnSync(process.execPath, [nativeEntry, '--version'], {
      cwd: electronRoot,
      encoding: 'utf8',
    })
    expect(version.error).toBeUndefined()
    expect(version.status, version.stderr || version.stdout).toBe(0)
    expect(version.stdout).toMatch(/Version 7\./)

    const config = spawnSync(process.execPath, [nativeEntry, '--showConfig', '-p', 'tsconfig.json'], {
      cwd: electronRoot,
      encoding: 'utf8',
    })
    expect(config.error).toBeUndefined()
    expect(config.status, config.stderr || config.stdout).toBe(0)
    expect(JSON.parse(config.stdout).compilerOptions.module).toBe('node16')
  })
})
