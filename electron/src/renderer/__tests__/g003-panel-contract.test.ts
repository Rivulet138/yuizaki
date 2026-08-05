import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'


const readRendererSource = (relativePath: string) =>
  readFileSync(`src/renderer/${relativePath}`, 'utf8')


describe('G003 panel information architecture', () => {
  it('keeps raw memory operations behind an announced advanced disclosure', () => {
    const source = readRendererSource('domains/memory/views/MemoryPanel.vue')

    expect(source).toContain(':aria-expanded="advancedToolsVisible"')
    expect(source).toContain('v-if="advancedToolsVisible" plain :loading="rebuildIndexLoading"')
    expect(source).toContain('docSourceLabel(row)')
    expect(source).toContain('docScopeLabel(row)')
    expect(source).toContain('docExpiryLabel(row)')
  })

  it('keeps advanced pet engine controls in a native accessible disclosure', () => {
    const source = readRendererSource('domains/pet/views/PetControlPanel.vue')

    expect(source).toContain('<details class="pet-advanced-controls">')
    expect(source).toContain('<summary>')
    expect(source.indexOf('pet-advanced-controls')).toBeLessThan(source.indexOf('lipsync-card'))
    expect(source.indexOf('pet-advanced-controls')).toBeLessThan(source.indexOf('expression-card'))
  })

  it('uses summaries and canonical routes instead of duplicate workspace selectors', () => {
    const source = readRendererSource('app/WorkspaceDrawer.vue')

    expect(source).not.toContain('workspace-model-select')
    expect(source).not.toContain('workspace-tool-select')
    expect(source).not.toContain('workspace-mcp-select')
    expect(source).toContain('data-testid="workspace-model-summary"')
    expect(source).toContain('data-testid="workspace-memory-summary"')
    expect(source).toContain('data-testid="workspace-tool-summary"')
    expect(source).toContain('data-testid="workspace-mcp-summary"')
    expect(source).toContain("canonicalRoute('settings')")
    expect(source).toContain("canonicalRoute('memory')")
    expect(source).toContain("canonicalRoute('tool')")
    expect(source).toContain("canonicalRoute('agent-governance')")
  })
})
