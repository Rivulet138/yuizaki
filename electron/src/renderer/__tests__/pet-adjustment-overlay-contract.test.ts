import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('desktop pet adjustment overlay contract', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../pet-window.html'), 'utf8')

  it('provides a full-display modal overlay with save and cancel controls', () => {
    expect(source).toContain('class="pet-adjustment-overlay"')
    expect(source).toContain('role="dialog"')
    expect(source).toContain('id="pet-adjustment-save"')
    expect(source).toContain('id="pet-adjustment-cancel"')
    expect(source).toMatch(/\.interact-mode\s+\.pet-adjustment-overlay\s*\{[^}]*display:\s*block/s)
  })

  it('keeps motion optional for users who request reduced motion', () => {
    expect(source).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/)
  })
})
