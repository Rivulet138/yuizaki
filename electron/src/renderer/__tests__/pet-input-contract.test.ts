import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('pet input responsiveness contract', () => {
  it('keeps compositor readback out of the renderer hover hot path', () => {
    const renderer = readFileSync(resolve(process.cwd(), 'src/renderer/pet-renderer.ts'), 'utf8')

    expect(renderer).not.toContain('window.live2dApi?.pet?.hasVisiblePixel')
    expect(renderer).not.toContain('capturePage(')
  })
})
