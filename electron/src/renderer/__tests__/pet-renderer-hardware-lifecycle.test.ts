import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('pet renderer hardware lifecycle', () => {
  it('polls in-memory download progress instead of rescanning resource directories', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/renderer/domains/settings/views/SettingsPanel.vue'), 'utf8')

    expect(source).toContain('await resourceClient.progress()')
    expect(source).toContain("document.addEventListener('visibilitychange'")
    expect(source).toContain("document.removeEventListener('visibilitychange'")
  })
})
