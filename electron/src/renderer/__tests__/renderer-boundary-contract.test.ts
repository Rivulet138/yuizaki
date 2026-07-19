import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const rendererRoot = path.resolve(__dirname, '..')

const toPascalCase = (value: string): string => value
  .split('-')
  .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
  .join('')

const sourceFiles = (root: string): string[] => readdirSync(root)
  .flatMap((name) => {
    const target = path.join(root, name)
    if (statSync(target).isDirectory()) {
      return name === '__tests__' ? [] : sourceFiles(target)
    }
    return /\.(?:ts|vue)$/.test(name) ? [target] : []
  })

describe('renderer product boundaries', () => {
  it('keeps backend clients under the product-neutral api boundary', () => {
    expect(existsSync(path.join(rendererRoot, 'workbench'))).toBe(false)

    const legacyReferences = sourceFiles(rendererRoot)
      .flatMap((file) => readFileSync(file, 'utf8').split(/\r?\n/)
        .filter((line) => /workbench/i.test(line))
        .map((line) => `${path.relative(rendererRoot, file)}: ${line.trim()}`))

    expect(legacyReferences).toEqual([])
  })

  it('does not register the complete Element Plus icon package globally', () => {
    const mainSource = readFileSync(path.join(rendererRoot, 'main.ts'), 'utf8')
    const topbarSource = readFileSync(path.join(rendererRoot, 'app/AppTopbar.vue'), 'utf8')

    expect(mainSource).not.toContain('import * as ElementPlusIconsVue')
    expect(mainSource).not.toContain('Object.entries(ElementPlusIconsVue)')
    expect(topbarSource).toContain("from '@element-plus/icons-vue'")
  })

  it('registers every Element Plus template component without the complete plugin', () => {
    const installerPath = path.join(rendererRoot, 'app/element-plus.ts')
    expect(existsSync(installerPath)).toBe(true)

    const mainSource = readFileSync(path.join(rendererRoot, 'main.ts'), 'utf8')
    const installerSource = readFileSync(installerPath, 'utf8')
    const rendererSources = sourceFiles(rendererRoot)
    const rendererSource = rendererSources.map((file) => readFileSync(file, 'utf8')).join('\n')
    const usedComponentTags = new Set(rendererSources
      .filter((file) => file.endsWith('.vue'))
      .flatMap((file) => Array.from(readFileSync(file, 'utf8').matchAll(/<el-([a-z0-9-]+)/g))
        .map((match) => match[1] ?? '')))

    expect(mainSource).not.toContain("import ElementPlus from 'element-plus'")
    expect(mainSource).not.toContain('app.use(ElementPlus)')
    expect(mainSource).not.toContain("element-plus/dist/index.css")
    expect(installerSource.includes('app.use(ElLoading)')).toBe(rendererSource.includes('v-loading'))
    expect(installerSource.includes('element-plus/es/components/loading/style/css'))
      .toBe(rendererSource.includes('v-loading'))
    for (const componentTag of usedComponentTags) {
      const componentName = `El${toPascalCase(componentTag)}`
      expect(installerSource, `${componentName} is not registered`).toContain(componentName)
      expect(installerSource, `${componentTag} styles are not imported`)
        .toContain(`element-plus/es/components/${componentTag}/style/css`)
    }
    for (const serviceName of ['message', 'message-box']) {
      expect(installerSource, `${serviceName} service styles are not imported`)
        .toContain(`element-plus/es/components/${serviceName}/style/css`)
    }
  })
})
