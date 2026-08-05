import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('renderer window security contract', () => {
  it('keeps both privileged preload windows explicitly sandboxed', () => {
    const panelWindow = readFileSync(resolve(process.cwd(), 'src/main/window.ts'), 'utf8')
    const petWindow = readFileSync(resolve(process.cwd(), 'src/main/live2d-window.ts'), 'utf8')

    expect(panelWindow).toContain('sandbox: true')
    expect(petWindow).toContain('sandbox: true')
    expect(panelWindow).not.toContain('sandbox: false')
    expect(petWindow).not.toContain('sandbox: false')
    expect(panelWindow).toContain("buildPackagedRendererUrl('index.html'")
    expect(petWindow).toContain("buildPackagedRendererUrl(\n        'pet-window.html'")
    expect(panelWindow).not.toContain('.loadFile(')
    expect(petWindow).not.toContain('.loadFile(')
  })

  it('does not refocus or blur the pet while toggling mouse passthrough', () => {
    const petWindow = readFileSync(resolve(process.cwd(), 'src/main/live2d-window.ts'), 'utf8')

    expect(petWindow).not.toContain('this.win.blur()')
    expect(petWindow).not.toContain('this.win.focus()')
  })
})
