import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8')

describe('application orchestrator ownership', () => {
  it('keeps startup and route orchestration owned by AppShell only', () => {
    const appShell = source('src/renderer/app/AppShell.vue')
    const dialogs = source('src/renderer/app/components/dialogs/GlobalDialogs.vue')
    const promptPanel = source('src/renderer/domains/prompt/views/PromptPanel.vue')

    expect(appShell).toContain('useAppOrchestrator()')
    expect(dialogs).not.toContain('useAppOrchestrator()')
    expect(promptPanel).not.toContain('useAppOrchestrator()')
  })
})
